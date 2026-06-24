#!/usr/bin/env bash

set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  K3S_URL=https://10.40.96.3:6443 \
  K3S_TOKEN=... \
  ./linux-script/add-k3s-worker-over-ssh.sh <ssh-target> <node-ip> <flannel-iface> [node-name]

Example:
  K3S_URL=https://10.40.96.3:6443 \
  K3S_TOKEN=K10...::server:... \
  ./linux-script/add-k3s-worker-over-ssh.sh root@149.x.x.x 10.40.96.7 enp8s0 worker-4
EOF
}

require_env() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    echo "Missing required environment variable: ${name}" >&2
    exit 1
  fi
}

extract_ssh_host() {
  local ssh_target="$1"
  local host="${ssh_target##*@}"
  printf '%s\n' "${host}"
}

remove_stale_known_host() {
  local ssh_target="$1"
  local known_hosts_file="$2"
  local ssh_host

  ssh_host="$(extract_ssh_host "${ssh_target}")"

  mkdir -p "$(dirname "${known_hosts_file}")"
  touch "${known_hosts_file}"

  ssh-keygen -R "${ssh_host}" -f "${known_hosts_file}" >/dev/null 2>&1 || true
  ssh-keygen -R "[${ssh_host}]:22" -f "${known_hosts_file}" >/dev/null 2>&1 || true
}

main() {
  if [[ $# -lt 3 || $# -gt 4 ]]; then
    usage
    exit 1
  fi

  require_env K3S_URL
  require_env K3S_TOKEN

  local ssh_target="$1"
  local node_ip="$2"
  local flannel_iface="$3"
  local node_name="${4:-}"
  local local_script="linux-script/bootstrap-k3s-worker.py"
  local remote_script="/tmp/bootstrap-k3s-worker.py"
  local known_hosts_file="${SSH_KNOWN_HOSTS_FILE:-$HOME/.ssh/known_hosts}"
  local refresh_known_hosts="${REFRESH_KNOWN_HOSTS:-true}"
  local ssh_opts="${SSH_OPTS:-}"

  if [[ "${refresh_known_hosts}" == "true" ]]; then
    remove_stale_known_host "${ssh_target}" "${known_hosts_file}"
  fi

  if [[ -z "${ssh_opts}" ]]; then
    ssh_opts="-o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=${known_hosts_file}"
  fi

  scp ${ssh_opts} "${local_script}" "${ssh_target}:${remote_script}"

  ssh ${ssh_opts} "${ssh_target}" \
    "sudo env \
      K3S_URL='${K3S_URL}' \
      K3S_TOKEN='${K3S_TOKEN}' \
      NODE_IP='${node_ip}' \
      FLANNEL_IFACE='${flannel_iface}' \
      NODE_NAME='${node_name}' \
      bash -lc 'if ! command -v python3 >/dev/null 2>&1; then export DEBIAN_FRONTEND=noninteractive; apt-get update; apt-get install -y python3; fi; exec python3 ${remote_script}'"
}

main "$@"
