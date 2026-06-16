#!/usr/bin/env bash

set -euo pipefail

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    echo "This script must run as root." >&2
    exit 1
  fi
}

install_packages() {
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y \
    ca-certificates \
    curl \
    python3 \
    python3-pip \
    python3-venv \
    rsync
}

main() {
  require_root

  echo "Installing load generator base packages..."
  install_packages

  echo "Load generator bootstrap completed."
  python3 --version
  pip3 --version
}

main "$@"
