#!/usr/bin/env bash

set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  VULTR_LOAD_BALANCER_ID=<lb-id> \
  [SCALER_WORKER_NODE_NAME_PREFIX=k3s-worker] \
  [WORKER_E2E_SCRIPT_PATH=/workspace/linux-script/create-worker-e2e.sh] \
  ./linux-script/executor-create-worker.sh [node-name]

Example:
  VULTR_LOAD_BALANCER_ID=abcd1234 \
  SCALER_WORKER_NODE_NAME_PREFIX=k3s-worker \
  ./linux-script/executor-create-worker.sh
EOF
}

require_env() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    echo "Missing required environment variable: ${name}" >&2
    exit 1
  fi
}

sanitize_name_component() {
  local raw="$1"
  printf '%s' "${raw}" \
    | tr '[:upper:]' '[:lower:]' \
    | sed -E 's/[^a-z0-9-]+/-/g; s/^-+//; s/-+$//; s/-+/-/g'
}

generate_node_name() {
  local prefix="$1"
  local scaler_name="$2"
  local sanitized_prefix
  local sanitized_scaler_name

  sanitized_prefix="$(sanitize_name_component "${prefix}")"
  sanitized_scaler_name="$(sanitize_name_component "${scaler_name}")"

  if [[ -z "${sanitized_prefix}" ]]; then
    sanitized_prefix="k3s-worker"
  fi

  if [[ -z "${sanitized_scaler_name}" ]]; then
    sanitized_scaler_name="scaler"
  fi

  printf '%s-%s-%s-%04d\n' \
    "${sanitized_prefix}" \
    "${sanitized_scaler_name}" \
    "$(date +%s)" \
    "$(( RANDOM % 10000 ))"
}

main() {
  if [[ $# -gt 1 ]]; then
    usage
    exit 1
  fi

  require_env VULTR_LOAD_BALANCER_ID

  local node_name="${1:-}"
  local script_path="${WORKER_E2E_SCRIPT_PATH:-./linux-script/create-worker-e2e.sh}"
  local node_name_prefix="${SCALER_WORKER_NODE_NAME_PREFIX:-k3s-worker}"
  local scaler_name="${SCALER_NAME:-worker}"

  if [[ ! -x "${script_path}" ]]; then
    echo "Worker create script is not executable: ${script_path}" >&2
    exit 1
  fi

  if [[ -z "${node_name}" ]]; then
    node_name="$(generate_node_name "${node_name_prefix}" "${scaler_name}")"
  fi

  echo "Starting worker create flow for node ${node_name}..."
  exec "${script_path}" "${VULTR_LOAD_BALANCER_ID}" "${node_name}"
}

main "$@"
