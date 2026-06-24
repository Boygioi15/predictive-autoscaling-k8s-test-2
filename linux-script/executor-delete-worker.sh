#!/usr/bin/env bash

set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  VULTR_LOAD_BALANCER_ID=<lb-id> \
  [WORKER_TARGET_NODE_NAME=<node-name>] \
  [WORKER_TEARDOWN_SCRIPT_PATH=/workspace/linux-script/teardown-vultr-worker.py] \
  ./linux-script/executor-delete-worker.sh [node-name]

Example:
  VULTR_LOAD_BALANCER_ID=abcd1234 \
  ./linux-script/executor-delete-worker.sh k3s-worker-7
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
  if [[ $# -gt 1 ]]; then
    usage
    exit 1
  fi

  require_env VULTR_LOAD_BALANCER_ID

  local node_name="${1:-${WORKER_TARGET_NODE_NAME:-}}"
  local script_path="${WORKER_TEARDOWN_SCRIPT_PATH:-./linux-script/teardown-vultr-worker.py}"

  if [[ -z "${node_name}" ]]; then
    echo "Missing worker target node name. Pass it as an argument or WORKER_TARGET_NODE_NAME." >&2
    exit 1
  fi

  if [[ ! -x "${script_path}" ]]; then
    echo "Worker teardown script is not executable: ${script_path}" >&2
    exit 1
  fi

  echo "Starting worker delete flow for node ${node_name}..."
  exec "${script_path}" "${node_name}"
}

main "$@"
