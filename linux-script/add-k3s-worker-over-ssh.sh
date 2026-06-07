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
  local local_script="linux-script/bootstrap-k3s-worker.sh"
  local remote_script="/tmp/bootstrap-k3s-worker.sh"
  local ssh_opts="${SSH_OPTS:-}"

  scp ${ssh_opts} "${local_script}" "${ssh_target}:${remote_script}"

  ssh ${ssh_opts} "${ssh_target}" \
    "chmod +x ${remote_script} && sudo env \
      K3S_URL='${K3S_URL}' \
      K3S_TOKEN='${K3S_TOKEN}' \
      NODE_IP='${node_ip}' \
      FLANNEL_IFACE='${flannel_iface}' \
      NODE_NAME='${node_name}' \
      bash ${remote_script}"
}

main "$@"
