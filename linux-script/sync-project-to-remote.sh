#!/usr/bin/env bash

set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  [SSH_OPTS='-i ~/.ssh/id_ed25519 -o StrictHostKeyChecking=accept-new'] \
  ./linux-script/sync-project-to-remote.sh <ssh-target> [remote-project-dir]

Example:
  SSH_OPTS='-i ~/.ssh/id_ed25519 -o StrictHostKeyChecking=accept-new' \
  ./linux-script/sync-project-to-remote.sh root@149.28.132.166 ~/predictive-autoscaling-k8s-test
EOF
}

require_command() {
  local name="$1"
  if ! command -v "${name}" >/dev/null 2>&1; then
    echo "Missing required command: ${name}" >&2
    exit 1
  fi
}

main() {
  if [[ $# -lt 1 || $# -gt 2 ]]; then
    usage
    exit 1
  fi

  require_command rsync
  require_command ssh

  local ssh_target="$1"
  local remote_project_dir="${2:-~/predictive-autoscaling-k8s-test}"
  local ssh_opts="${SSH_OPTS:-}"

  if [[ -n "${ssh_opts}" ]]; then
    ssh ${ssh_opts} "${ssh_target}" "mkdir -p ${remote_project_dir}"
  else
    ssh "${ssh_target}" "mkdir -p ${remote_project_dir}"
  fi

  rsync -avz --progress \
    -e "ssh ${ssh_opts}" \
    --include "shares/" \
    --include "shares/test_script.csv" \
    --exclude ".git/" \
    --exclude "__pycache__/" \
    --exclude ".pytest_cache/" \
    --exclude ".venv/" \
    --exclude "venv/" \
    --exclude "node_modules/" \
    --exclude "dist/" \
    --exclude "build/" \
    --exclude ".next/" \
    --exclude "*.pyc" \
    --exclude "*.log" \
    --exclude "shares/**" \
    --exclude "work-log/" \
    ./ "${ssh_target}:${remote_project_dir}/"
}

main "$@"
