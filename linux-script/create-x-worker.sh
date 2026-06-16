#!/usr/bin/env bash

set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  VULTR_LOAD_BALANCER_ID=<lb-id> \
  ./linux-script/create-x-worker.sh <prefix> <count>

Example:
  VULTR_LOAD_BALANCER_ID=abcd1234 \
  ./linux-script/create-x-worker.sh baseline 15

This starts:
  baseline-1
  baseline-2
  ...
  baseline-15

Each worker is created asynchronously through executor-create-worker.sh.
EOF
}

main() {
  if [[ $# -ne 2 ]]; then
    usage
    exit 1
  fi

  local prefix="$1"
  local count="$2"
  local script_path="./linux-script/executor-create-worker.sh"
  local logs_dir="./work-log/create-x-worker"

  if [[ -z "${VULTR_LOAD_BALANCER_ID:-}" ]]; then
    echo "Missing required environment variable: VULTR_LOAD_BALANCER_ID" >&2
    exit 1
  fi

  if [[ ! "${count}" =~ ^[0-9]+$ ]] || (( count < 1 )); then
    echo "Count must be a positive integer." >&2
    exit 1
  fi

  if [[ ! -x "${script_path}" ]]; then
    echo "Worker executor is not executable: ${script_path}" >&2
    exit 1
  fi

  mkdir -p "${logs_dir}"

  local -a pids=()
  local -a names=()
  local i

  for (( i = 1; i <= count; i++ )); do
    local node_name="${prefix}-${i}"
    local log_file="${logs_dir}/${node_name}.log"

    echo "Launching ${node_name}..."
    "${script_path}" "${node_name}" >"${log_file}" 2>&1 &
    pids+=("$!")
    names+=("${node_name}")
  done

  local failures=0

  for (( i = 0; i < ${#pids[@]}; i++ )); do
    if wait "${pids[i]}"; then
      echo "Completed ${names[i]}."
    else
      echo "Failed ${names[i]}. Check ${logs_dir}/${names[i]}.log" >&2
      failures=$((failures + 1))
    fi
  done

  if (( failures > 0 )); then
    echo "${failures} worker create job(s) failed." >&2
    exit 1
  fi

  echo "All ${count} worker create jobs completed successfully."
}

main "$@"
