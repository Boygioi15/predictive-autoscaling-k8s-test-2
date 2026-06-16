#!/usr/bin/env bash

set -euo pipefail

lb_result_file=""
loadgen_result_file=""
master_result_file=""
master_env_file=""

cleanup_temp_files() {
  rm -f \
    "${lb_result_file:-}" \
    "${loadgen_result_file:-}" \
    "${master_result_file:-}" \
    "${master_env_file:-}"
}

trap cleanup_temp_files EXIT

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
  [BOOTSTRAP_SSH_PRIVATE_KEY_FILE=~/.ssh/id_ed25519] \
  ./linux-script/create-cluster-base.sh <cluster-prefix>

What it creates:
  - <cluster-prefix>-lb
  - <cluster-prefix>-loadgen
  - <cluster-prefix>-master

What it bootstraps:
  - repo sync to load generator and master
  - Python on the load generator
  - k3s server + Helm + monitoring + custom scaler on the master
  - local vm-bookkeep.json update
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

expand_local_path() {
  python3 - "$1" <<'PY'
from pathlib import Path
import sys

print(Path(sys.argv[1]).expanduser())
PY
}

resolve_private_key_path() {
  if [[ -n "${BOOTSTRAP_SSH_PRIVATE_KEY_FILE:-}" ]]; then
    printf '%s\n' "${BOOTSTRAP_SSH_PRIVATE_KEY_FILE}"
    return
  fi

  if [[ -n "${VULTR_ROOT_PUBLIC_KEY_FILE:-}" && "${VULTR_ROOT_PUBLIC_KEY_FILE}" == *.pub ]]; then
    printf '%s\n' "${VULTR_ROOT_PUBLIC_KEY_FILE%.pub}"
    return
  fi

  echo "Unable to derive BOOTSTRAP_SSH_PRIVATE_KEY_FILE. Set it explicitly." >&2
  exit 1
}

read_result_field() {
  local path="$1"
  local field="$2"

  python3 - "$path" "$field" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
field = sys.argv[2]
data = json.loads(path.read_text(encoding="utf-8"))
print(data.get(field, ""))
PY
}

extract_ssh_host() {
  local ssh_target="$1"
  local host="${ssh_target##*@}"
  printf '%s\n' "${host}"
}

remove_stale_known_host() {
  local ssh_target="$1"
  local known_hosts_file="${SSH_KNOWN_HOSTS_FILE:-$HOME/.ssh/known_hosts}"
  local ssh_host

  ssh_host="$(extract_ssh_host "${ssh_target}")"

  mkdir -p "$(dirname "${known_hosts_file}")"
  touch "${known_hosts_file}"

  ssh-keygen -R "${ssh_host}" -f "${known_hosts_file}" >/dev/null 2>&1 || true
  ssh-keygen -R "[${ssh_host}]:22" -f "${known_hosts_file}" >/dev/null 2>&1 || true
}

ensure_local_ssh_opts() {
  local private_key_file="$1"
  local known_hosts_file="${SSH_KNOWN_HOSTS_FILE:-$HOME/.ssh/known_hosts}"

  mkdir -p "$(dirname "${known_hosts_file}")"
  touch "${known_hosts_file}"

  if [[ -n "${LOCAL_SSH_OPTS:-}" ]]; then
    return
  fi

  if [[ -n "${SSH_OPTS:-}" ]]; then
    LOCAL_SSH_OPTS="${SSH_OPTS}"
    return
  fi

  LOCAL_SSH_OPTS="-i ${private_key_file} -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=${known_hosts_file} -o ConnectTimeout=5"
}

wait_for_ssh_ready() {
  local ssh_target="$1"
  local timeout_seconds="${SSH_READY_TIMEOUT_SECONDS:-300}"
  local poll_interval_seconds="${SSH_READY_POLL_INTERVAL_SECONDS:-5}"
  local deadline=$((SECONDS + timeout_seconds))
  local attempt=1

  echo "Waiting for SSH on ${ssh_target}..."
  while (( SECONDS < deadline )); do
    if ssh ${LOCAL_SSH_OPTS} "${ssh_target}" "true" >/dev/null 2>&1; then
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

ssh_target_for_mode() {
  local public_ip="$1"
  local private_ip="$2"
  local host_mode="$3"

  case "${host_mode}" in
    public)
      printf '%s\n' "${public_ip}"
      ;;
    private)
      if [[ -z "${private_ip}" ]]; then
        echo "Requested private SSH host mode but no private IP is available." >&2
        exit 1
      fi
      printf '%s\n' "${private_ip}"
      ;;
    *)
      echo "Unknown host mode: ${host_mode}" >&2
      exit 1
      ;;
  esac
}

configure_ufw() {
  if ! command -v ufw >/dev/null 2>&1; then
    echo "ufw not installed, skipping firewall rules."
    return
  fi

  ufw allow 22/tcp
  ufw allow 80/tcp
  ufw allow 8472/udp
  ufw allow 6443/tcp
  ufw allow 6443/udp
  ufw allow 10250/tcp

  if [[ "${ALLOW_HTTPS:-false}" == "true" ]]; then
    ufw allow 443/tcp
  fi
}

run_remote() {
  local ssh_target="$1"
  shift
  ssh ${LOCAL_SSH_OPTS} "${ssh_target}" "$@"
}

copy_file_to_remote() {
  local source_path="$1"
  local ssh_target="$2"
  local remote_path="$3"

  scp ${LOCAL_SSH_OPTS} "${source_path}" "${ssh_target}:${remote_path}"
}

ensure_remote_rsync() {
  local ssh_target="$1"
  echo "Installing rsync on ${ssh_target} so project sync can run..."
  run_remote "${ssh_target}" "export DEBIAN_FRONTEND=noninteractive && apt-get update && apt-get install -y rsync"
}

sync_repo() {
  local ssh_target="$1"
  local remote_project_dir="$2"
  SSH_OPTS="${LOCAL_SSH_OPTS}" ./linux-script/sync-project-to-remote.sh "${ssh_target}" "${remote_project_dir}"
}

configure_ufw_over_ssh() {
  local ssh_target="$1"
  local allow_https="${ALLOW_HTTPS:-false}"

  ssh ${LOCAL_SSH_OPTS} "${ssh_target}" "ALLOW_HTTPS='${allow_https}' bash -s" <<'EOF'
set -euo pipefail

configure_ufw() {
  if ! command -v ufw >/dev/null 2>&1; then
    echo "ufw not installed, skipping firewall rules."
    return
  fi

  ufw allow 22/tcp
  ufw allow 80/tcp
  ufw allow 8472/udp
  ufw allow 6443/tcp
  ufw allow 6443/udp
  ufw allow 10250/tcp

  if [[ "${ALLOW_HTTPS:-false}" == "true" ]]; then
    ufw allow 443/tcp
  fi
}

configure_ufw
EOF
}

create_vm_with_role_env() {
  local result_file="$1"
  local node_name="$2"
  local region="$3"
  local plan="$4"
  local os_id="$5"
  local firewall_group_id="$6"
  local vpc_id="$7"
  local ssh_key_ids="$8"
  local root_public_key_file="$9"
  local extra_root_public_key="${10}"
  local local_bootstrap_host_mode="${LOCAL_BOOTSTRAP_SSH_HOST_MODE:-public}"
  local ssh_user="${VULTR_BOOTSTRAP_SSH_USER:-root}"
  local public_ip
  local private_ip
  local ssh_host
  local ssh_target

  (
    export VULTR_REGION="${region}"
    export VULTR_PLAN="${plan}"
    export VULTR_OS_ID="${os_id}"
    export VULTR_SSH_KEY_IDS="${ssh_key_ids}"
    export CREATE_RESULT_FILE="${result_file}"

    if [[ -n "${firewall_group_id}" ]]; then
      export VULTR_FIREWALL_GROUP_ID="${firewall_group_id}"
    else
      unset VULTR_FIREWALL_GROUP_ID || true
    fi

    if [[ -n "${vpc_id}" ]]; then
      export VULTR_VPC_ID="${vpc_id}"
    else
      unset VULTR_VPC_ID || true
    fi

    if [[ -n "${root_public_key_file}" ]]; then
      export VULTR_ROOT_PUBLIC_KEY_FILE="${root_public_key_file}"
    else
      unset VULTR_ROOT_PUBLIC_KEY_FILE || true
    fi

    if [[ -n "${extra_root_public_key}" ]]; then
      export VULTR_ROOT_PUBLIC_KEY="${extra_root_public_key}"
    else
      unset VULTR_ROOT_PUBLIC_KEY || true
    fi

    ./linux-script/create-vultr-worker.sh "${node_name}"
  )

  public_ip="$(read_result_field "${result_file}" public_ip)"
  private_ip="$(read_result_field "${result_file}" private_ip)"
  ssh_host="$(ssh_target_for_mode "${public_ip}" "${private_ip}" "${local_bootstrap_host_mode}")"
  ssh_target="${ssh_user}@${ssh_host}"

  remove_stale_known_host "${ssh_target}"
  wait_for_ssh_ready "${ssh_target}"
  configure_ufw_over_ssh "${ssh_target}"
}

update_bookkeep() {
  local prefix="$1"
  local master_file="$2"
  local loadgen_file="$3"
  local lb_file="$4"

  python3 - "$prefix" "$master_file" "$loadgen_file" "$lb_file" <<'PY'
import json
import sys
from pathlib import Path

prefix, master_file, loadgen_file, lb_file = sys.argv[1:]
bookkeep_path = Path("vm-bookkeep.json")

if bookkeep_path.exists():
    data = json.loads(bookkeep_path.read_text(encoding="utf-8"))
else:
    data = {}

def normalize(path_str):
    raw = json.loads(Path(path_str).read_text(encoding="utf-8"))
    return {
        "id": raw.get("instance_id", ""),
        "public_ip": raw.get("public_ip", ""),
        "private_ip": raw.get("private_ip", ""),
    }

data[prefix] = {
    "master": normalize(master_file),
    "load_generator": normalize(loadgen_file),
    "lb": normalize(lb_file),
}

bookkeep_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
PY
}

write_master_env_file() {
  local env_file="$1"
  local prefix="$2"
  local master_name="$3"
  local master_public_ip="$4"
  local master_private_ip="$5"
  local lb_id="$6"
  local worker_region="$7"
  local worker_plan="$8"
  local worker_os_id="$9"
  local worker_firewall_group_id="${10}"
  local worker_vpc_id="${11}"
  local worker_ssh_key_ids="${12}"
  local vm_job_private_key_path="${13}"
  local vm_job_public_key_path="${14}"
  local project_dir="${15}"

  : > "${env_file}"

  append_env_line() {
    local key="$1"
    local value="$2"
    printf '%s=%q\n' "${key}" "${value}" >> "${env_file}"
  }

  append_env_line "CLUSTER_PREFIX" "${prefix}"
  append_env_line "MASTER_NODE_NAME" "${master_name}"
  append_env_line "MASTER_PUBLIC_IP" "${master_public_ip}"
  append_env_line "MASTER_PRIVATE_IP" "${master_private_ip}"
  append_env_line "PROJECT_DIR" "${project_dir}"
  append_env_line "FLANNEL_IFACE_DEFAULT" "${FLANNEL_IFACE_DEFAULT:-enp8s0}"
  append_env_line "K3S_CHANNEL" "${K3S_CHANNEL:-stable}"
  append_env_line "CUSTOM_SCALER_IMAGE" "${CUSTOM_SCALER_IMAGE:-docker.io/boygioi/custom-scaler:latest}"
  append_env_line "INSTALL_MONITORING" "${INSTALL_MONITORING:-true}"
  append_env_line "INSTALL_INGRESS" "${INSTALL_INGRESS:-false}"
  append_env_line "DEPLOY_CUSTOM_SCALER" "${DEPLOY_CUSTOM_SCALER:-true}"
  append_env_line "APPLY_CUSTOM_SCALER_SAMPLE" "${APPLY_CUSTOM_SCALER_SAMPLE:-true}"
  append_env_line "WORKER_VULTR_REGION" "${worker_region}"
  append_env_line "WORKER_VULTR_PLAN" "${worker_plan}"
  append_env_line "WORKER_VULTR_OS_ID" "${worker_os_id}"
  append_env_line "WORKER_VULTR_FIREWALL_GROUP_ID" "${worker_firewall_group_id}"
  append_env_line "WORKER_VULTR_VPC_ID" "${worker_vpc_id}"
  append_env_line "WORKER_VULTR_SSH_KEY_IDS" "${worker_ssh_key_ids}"
  append_env_line "WORKER_BOOTSTRAP_SSH_HOST_MODE" "${WORKER_BOOTSTRAP_SSH_HOST_MODE:-private}"
  append_env_line "VULTR_BOOTSTRAP_SSH_USER" "${VULTR_BOOTSTRAP_SSH_USER:-root}"
  append_env_line "VULTR_LOAD_BALANCER_ID" "${lb_id}"
  append_env_line "VULTR_API_KEY" "${VULTR_API_KEY}"
  append_env_line "VM_JOB_PRIVATE_KEY_PATH" "${vm_job_private_key_path}"
  append_env_line "VM_JOB_PUBLIC_KEY_PATH" "${vm_job_public_key_path}"
}

main() {
  if [[ $# -ne 1 ]]; then
    usage
    exit 1
  fi

  require_command python3
  require_command ssh
  require_command scp
  require_command rsync
  require_command curl
  require_command mktemp

  require_env VULTR_API_KEY
  require_env VULTR_REGION
  require_env VULTR_PLAN
  require_env VULTR_OS_ID

  local prefix="$1"
  local lb_name="${prefix}-lb"
  local loadgen_name="${prefix}-loadgen"
  local master_name="${prefix}-master"
  local remote_project_dir="${REMOTE_PROJECT_DIR:-~/predictive-autoscaling-k8s-test}"
  local local_bootstrap_host_mode="${LOCAL_BOOTSTRAP_SSH_HOST_MODE:-public}"
  local ssh_user="${VULTR_BOOTSTRAP_SSH_USER:-root}"
  local private_key_file
  local public_key_file="${VULTR_ROOT_PUBLIC_KEY_FILE:-}"
  local inline_public_key="${VULTR_ROOT_PUBLIC_KEY:-}"
  local vm_job_public_key_remote="/root/.ssh/id_ed25519.pub"
  local vm_job_private_key_remote="/root/.ssh/id_ed25519"
  local worker_region="${WORKER_VULTR_REGION:-${VULTR_REGION}}"
  local worker_plan="${WORKER_VULTR_PLAN:-${VULTR_PLAN}}"
  local worker_os_id="${WORKER_VULTR_OS_ID:-${VULTR_OS_ID}}"
  local worker_firewall_group_id="${WORKER_VULTR_FIREWALL_GROUP_ID:-${VULTR_FIREWALL_GROUP_ID:-}}"
  local worker_vpc_id="${WORKER_VULTR_VPC_ID:-${VULTR_VPC_ID:-}}"
  local worker_ssh_key_ids="${WORKER_VULTR_SSH_KEY_IDS:-${VULTR_SSH_KEY_IDS}}"
  local master_region="${VULTR_MASTER_REGION:-${VULTR_REGION}}"
  local master_plan="${VULTR_MASTER_PLAN:-${VULTR_PLAN}}"
  local master_os_id="${VULTR_MASTER_OS_ID:-${VULTR_OS_ID}}"
  local master_firewall_group_id="${VULTR_MASTER_FIREWALL_GROUP_ID:-${VULTR_FIREWALL_GROUP_ID:-}}"
  local master_vpc_id="${VULTR_MASTER_VPC_ID:-${VULTR_VPC_ID:-}}"
  local master_ssh_key_ids="${VULTR_MASTER_SSH_KEY_IDS:-${VULTR_SSH_KEY_IDS}}"
  local loadgen_region="${VULTR_LOAD_GENERATOR_REGION:-nrt}"
  local loadgen_plan="${VULTR_LOAD_GENERATOR_PLAN:-${VULTR_PLAN}}"
  local loadgen_os_id="${VULTR_LOAD_GENERATOR_OS_ID:-${VULTR_OS_ID}}"
  local loadgen_firewall_group_id="${VULTR_LOAD_GENERATOR_FIREWALL_GROUP_ID:-${VULTR_FIREWALL_GROUP_ID:-}}"
  local loadgen_vpc_id="${VULTR_LOAD_GENERATOR_VPC_ID:-}"
  local loadgen_ssh_key_ids="${VULTR_LOAD_GENERATOR_SSH_KEY_IDS:-${VULTR_SSH_KEY_IDS}}"

  private_key_file="$(resolve_private_key_path)"
  private_key_file="$(expand_local_path "${private_key_file}")"
  ensure_local_ssh_opts "${private_key_file}"

  if [[ -n "${public_key_file}" ]]; then
    public_key_file="$(expand_local_path "${public_key_file}")"
  fi

  if [[ -n "${public_key_file}" && ! -f "${public_key_file}" ]]; then
    echo "Root public key file not found: ${public_key_file}" >&2
    exit 1
  fi

  if [[ ! -f "${private_key_file}" ]]; then
    echo "Bootstrap SSH private key file not found: ${private_key_file}" >&2
    exit 1
  fi

  lb_result_file="$(mktemp)"
  loadgen_result_file="$(mktemp)"
  master_result_file="$(mktemp)"
  master_env_file="$(mktemp)"

  echo "Step 1/7: create load balancer ${lb_name}..."
  CREATE_RESULT_FILE="${lb_result_file}" \
    VULTR_LB_REGION="${VULTR_LB_REGION:-${master_region}}" \
    VULTR_LB_NODES="${VULTR_LB_NODES:-3}" \
    ./linux-script/create-vultr-load-balancer.sh "${lb_name}"

  echo
  echo "Step 2/7: create load generator VM ${loadgen_name}..."
  create_vm_with_role_env \
    "${loadgen_result_file}" \
    "${loadgen_name}" \
    "${loadgen_region}" \
    "${loadgen_plan}" \
    "${loadgen_os_id}" \
    "${loadgen_firewall_group_id}" \
    "${loadgen_vpc_id}" \
    "${loadgen_ssh_key_ids}" \
    "${public_key_file}" \
    "${inline_public_key}"

  echo
  echo "Step 3/7: create master VM ${master_name}..."
  create_vm_with_role_env \
    "${master_result_file}" \
    "${master_name}" \
    "${master_region}" \
    "${master_plan}" \
    "${master_os_id}" \
    "${master_firewall_group_id}" \
    "${master_vpc_id}" \
    "${master_ssh_key_ids}" \
    "${public_key_file}" \
    "${inline_public_key}"

  update_bookkeep "${prefix}" "${master_result_file}" "${loadgen_result_file}" "${lb_result_file}"

  local loadgen_public_ip
  local loadgen_private_ip
  local master_public_ip
  local master_private_ip
  local lb_id
  local loadgen_host
  local master_host
  local loadgen_target
  local master_target

  loadgen_public_ip="$(read_result_field "${loadgen_result_file}" public_ip)"
  loadgen_private_ip="$(read_result_field "${loadgen_result_file}" private_ip)"
  master_public_ip="$(read_result_field "${master_result_file}" public_ip)"
  master_private_ip="$(read_result_field "${master_result_file}" private_ip)"
  lb_id="$(read_result_field "${lb_result_file}" instance_id)"

  loadgen_host="$(ssh_target_for_mode "${loadgen_public_ip}" "${loadgen_private_ip}" "${local_bootstrap_host_mode}")"
  master_host="$(ssh_target_for_mode "${master_public_ip}" "${master_private_ip}" "${local_bootstrap_host_mode}")"
  loadgen_target="${ssh_user}@${loadgen_host}"
  master_target="${ssh_user}@${master_host}"

  echo
  echo "Step 4/7: wait for SSH access..."
  remove_stale_known_host "${loadgen_target}"
  remove_stale_known_host "${master_target}"
  wait_for_ssh_ready "${loadgen_target}"
  wait_for_ssh_ready "${master_target}"

  echo
  echo "Step 5/7: sync the project to both VMs..."
  ensure_remote_rsync "${loadgen_target}"
  ensure_remote_rsync "${master_target}"
  sync_repo "${loadgen_target}" "${remote_project_dir}"
  sync_repo "${master_target}" "${remote_project_dir}"

  echo
  echo "Step 6/7: bootstrap the load generator..."
  run_remote "${loadgen_target}" "cd ${remote_project_dir} && bash linux-script/bootstrap-load-generator.sh"

  if [[ "${DEPLOY_CUSTOM_SCALER:-true}" == "true" ]]; then
    echo "Copying the worker bootstrap SSH keypair to the master..."
    run_remote "${master_target}" "mkdir -p /root/.ssh && chmod 700 /root/.ssh"
    copy_file_to_remote "${private_key_file}" "${master_target}" "${vm_job_private_key_remote}"

    local expanded_public_key_file="${public_key_file}"
    if [[ -z "${expanded_public_key_file}" ]]; then
      expanded_public_key_file="${private_key_file}.pub"
    fi
    expanded_public_key_file="$(expand_local_path "${expanded_public_key_file}")"
    if [[ ! -f "${expanded_public_key_file}" ]]; then
      echo "Worker bootstrap public key file not found: ${expanded_public_key_file}" >&2
      exit 1
    fi
    copy_file_to_remote "${expanded_public_key_file}" "${master_target}" "${vm_job_public_key_remote}"
    run_remote "${master_target}" "chmod 600 ${vm_job_private_key_remote} && chmod 644 ${vm_job_public_key_remote}"
  fi

  echo
  echo "Step 7/7: bootstrap the master..."
  write_master_env_file \
    "${master_env_file}" \
    "${prefix}" \
    "${master_name}" \
    "${master_public_ip}" \
    "${master_private_ip}" \
    "${lb_id}" \
    "${worker_region}" \
    "${worker_plan}" \
    "${worker_os_id}" \
    "${worker_firewall_group_id}" \
    "${worker_vpc_id}" \
    "${worker_ssh_key_ids}" \
    "${vm_job_private_key_remote}" \
    "${vm_job_public_key_remote}" \
    "${remote_project_dir}"
  copy_file_to_remote "${master_env_file}" "${master_target}" "/tmp/bootstrap-k3s-master.env"
  run_remote "${master_target}" "set -a && source /tmp/bootstrap-k3s-master.env && set +a && cd ${remote_project_dir} && bash linux-script/bootstrap-k3s-master.sh"

  echo
  echo "Cluster base provisioning completed."
  echo "  prefix: ${prefix}"
  echo "  load-balancer-id: ${lb_id}"
  echo "  master-public-ip: ${master_public_ip}"
  echo "  master-private-ip: ${master_private_ip:-<none>}"
  echo "  load-generator-public-ip: ${loadgen_public_ip}"
  echo "  bookkeeping: vm-bookkeep.json"
}

main "$@"
