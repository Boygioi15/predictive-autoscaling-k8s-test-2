#!/usr/bin/env bash

set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  VULTR_API_KEY=... \
  VULTR_REGION=sgp \
  VULTR_PLAN=vc2-2c-4gb \
  VULTR_OS_ID=2284 \
  VULTR_FIREWALL_GROUP_ID=<firewall-id> \
  VULTR_VPC_ID=<vpc-id> \
  VULTR_SSH_KEY_IDS=<ssh-key-id>[,<ssh-key-id>...] \
  VULTR_ROOT_PUBLIC_KEY_FILE=~/.ssh/id_ed25519.pub \
  K3S_URL=https://10.40.96.3:6443 \
  K3S_TOKEN=... \
  ./linux-script/create-worker-e2e.sh <load-balancer-id> [node-name]

Example:
  VULTR_API_KEY=... \
  VULTR_REGION=sgp \
  VULTR_PLAN=vc2-2c-4gb \
  VULTR_OS_ID=2284 \
  VULTR_FIREWALL_GROUP_ID=abcd1234 \
  VULTR_VPC_ID=dcba4321 \
  VULTR_SSH_KEY_IDS=key-1 \
  VULTR_ROOT_PUBLIC_KEY_FILE=~/.ssh/id_ed25519.pub \
  K3S_URL=https://10.40.96.3:6443 \
  K3S_TOKEN=K10...::server:... \
  ./linux-script/create-worker-e2e.sh lb-1234 worker-5
EOF
}

require_env() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    echo "Missing required environment variable: ${name}" >&2
    exit 1
  fi
}

require_command() {
  local name="$1"
  if ! command -v "${name}" >/dev/null 2>&1; then
    echo "Missing required command: ${name}" >&2
    exit 1
  fi
}

extract_ssh_host() {
  local ssh_target="$1"
  local host="${ssh_target##*@}"
  printf '%s\n' "${host}"
}

generate_node_name() {
  local prefix="${WORKER_NODE_NAME_PREFIX:-k3s-worker}"
  printf '%s-%s-%04d\n' "${prefix}" "$(date +%s)" "$(( RANDOM % 10000 ))"
}

read_create_result_field() {
  local field="$1"
  python3 - "$CREATE_RESULT_PATH" "$field" <<'PY'
import json
import sys
from pathlib import Path

result_path = Path(sys.argv[1])
field = sys.argv[2]

data = json.loads(result_path.read_text(encoding="utf-8"))
value = data.get(field, "")
print(value)
PY
}

wait_for_node_ready() {
  local node_name="$1"
  local timeout="${KUBECTL_NODE_READY_TIMEOUT:-300s}"
  local registration_timeout_seconds="${KUBECTL_NODE_REGISTRATION_TIMEOUT_SECONDS:-300}"
  local poll_interval_seconds="${KUBECTL_NODE_POLL_INTERVAL_SECONDS:-5}"
  local deadline=$((SECONDS + registration_timeout_seconds))

  echo "Waiting for node ${node_name} to register with the cluster..."
  while (( SECONDS < deadline )); do
    if kubectl get node "${node_name}" >/dev/null 2>&1; then
      break
    fi
    sleep "${poll_interval_seconds}"
  done

  if ! kubectl get node "${node_name}" >/dev/null 2>&1; then
    echo "Timed out waiting for node ${node_name} to appear in the cluster." >&2
    exit 1
  fi

  echo "Waiting for node ${node_name} to become Ready..."
  kubectl wait --for=condition=Ready "node/${node_name}" --timeout="${timeout}"
}

remove_stale_known_host() {
  local ssh_target="$1"
  local known_hosts_file="${SSH_KNOWN_HOSTS_FILE:-$HOME/.ssh/known_hosts}"
  local ssh_host

  ssh_host="$(extract_ssh_host "${ssh_target}")"

  mkdir -p "$(dirname "${known_hosts_file}")"
  touch "${known_hosts_file}"

  echo "Removing stale SSH host key for ${ssh_host}..."
  ssh-keygen -R "${ssh_host}" -f "${known_hosts_file}" >/dev/null 2>&1 || true
  ssh-keygen -R "[${ssh_host}]:22" -f "${known_hosts_file}" >/dev/null 2>&1 || true
}

wait_for_ssh_ready() {
  local ssh_target="$1"
  local known_hosts_file="${SSH_KNOWN_HOSTS_FILE:-$HOME/.ssh/known_hosts}"
  local timeout_seconds="${SSH_READY_TIMEOUT_SECONDS:-300}"
  local poll_interval_seconds="${SSH_READY_POLL_INTERVAL_SECONDS:-5}"
  local connect_timeout_seconds="${SSH_READY_CONNECT_TIMEOUT_SECONDS:-5}"
  local deadline=$((SECONDS + timeout_seconds))
  local ssh_opts="${SSH_OPTS:-}"
  local attempt=1

  if [[ -z "${ssh_opts}" ]]; then
    ssh_opts="-o BatchMode=yes -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=${known_hosts_file} -o ConnectTimeout=${connect_timeout_seconds}"
  fi

  echo "Waiting for SSH on ${ssh_target}..."
  while (( SECONDS < deadline )); do
    if ssh -v ${ssh_opts} "${ssh_target}" "true" >/dev/null; then
      echo "SSH is ready on ${ssh_target}."
      return
    fi

    echo "  SSH not ready yet on ${ssh_target} (attempt ${attempt}), retrying in ${poll_interval_seconds}s..."
    attempt=$((attempt + 1))
    sleep "${poll_interval_seconds}"
  done

  echo "Timed out waiting for SSH on ${ssh_target} after ${timeout_seconds}s." >&2
  exit 1
}

main() {
  if [[ $# -lt 1 || $# -gt 2 ]]; then
    usage
    exit 1
  fi

  require_command curl
  require_command kubectl
  require_command mktemp
  require_command python3
  require_env K3S_URL
  require_env K3S_TOKEN
  require_env VULTR_API_KEY
  require_env VULTR_REGION
  require_env VULTR_PLAN
  require_env VULTR_OS_ID

  local load_balancer_id="$1"
  local node_name="${2:-}"
  local flannel_iface="${FLANNEL_IFACE_DEFAULT:-enp8s0}"
  local bootstrap_ssh_user="${VULTR_BOOTSTRAP_SSH_USER:-root}"
  local bootstrap_ssh_host_mode="${BOOTSTRAP_SSH_HOST_MODE:-private}"
  local ssh_target_host=""

  if [[ -z "${node_name}" ]]; then
    node_name="$(generate_node_name)"
  fi

  CREATE_RESULT_PATH="$(mktemp)"
  trap 'rm -f "${CREATE_RESULT_PATH}"' EXIT

  echo "Step 1/4: create worker VM ${node_name}..."
  CREATE_RESULT_FILE="${CREATE_RESULT_PATH}" \
    ./linux-script/create-vultr-worker.sh "${node_name}"

  local public_ip
  local private_ip
  public_ip="$(read_create_result_field public_ip)"
  private_ip="$(read_create_result_field private_ip)"

  if [[ -z "${public_ip}" || -z "${private_ip}" ]]; then
    echo "Create result file did not include both public and private IPs." >&2
    exit 1
  fi

  case "${bootstrap_ssh_host_mode}" in
    public)
      ssh_target_host="${public_ip}"
      ;;
    private)
      ssh_target_host="${private_ip}"
      ;;
    *)
      echo "BOOTSTRAP_SSH_HOST_MODE must be either public or private. Got: ${bootstrap_ssh_host_mode}" >&2
      exit 1
      ;;
  esac

  remove_stale_known_host "${private_ip}"
  remove_stale_known_host "${bootstrap_ssh_user}@${ssh_target_host}"
  wait_for_ssh_ready "${bootstrap_ssh_user}@${ssh_target_host}"

  echo
  echo "Step 2/4: join node ${node_name} to the cluster..."
  ./linux-script/add-k3s-worker-over-ssh.sh "${bootstrap_ssh_user}@${ssh_target_host}" "${private_ip}" "${flannel_iface}" "${node_name}"

  echo
  echo "Step 3/4: wait for node readiness..."
  wait_for_node_ready "${node_name}"

  echo
  echo "Step 4/4: attach VM to load balancer..."
  ./linux-script/attach-vm-to-lb.sh "${load_balancer_id}" "${public_ip}"

  echo
  echo "Worker create flow completed:"
  python3 - "$CREATE_RESULT_PATH" "$load_balancer_id" <<'PY'
import json
import sys
from pathlib import Path

result_path = Path(sys.argv[1])
load_balancer_id = sys.argv[2]

data = json.loads(result_path.read_text(encoding="utf-8"))
summary = {
    "node_name": data.get("node_name"),
    "instance_id": data.get("instance_id"),
    "public_ip": data.get("public_ip"),
    "private_ip": data.get("private_ip"),
    "load_balancer_id": load_balancer_id,
}

print(json.dumps(summary, indent=2))
PY
}

main "$@"
