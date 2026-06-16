#!/usr/bin/env bash

set -euo pipefail

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    echo "This script must run as root." >&2
    exit 1
  fi
}

require_env() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    echo "Missing required environment variable: ${name}" >&2
    exit 1
  fi
}

derive_node_ip_from_iface() {
  local iface="$1"
  ip -4 -o addr show dev "${iface}" | awk 'NR==1 {split($4, a, "/"); print a[1]}'
}

derive_iface_from_node_ip() {
  local node_ip="$1"
  ip -4 -o addr show | awk -v ip="${node_ip}" 'index($4, ip "/") == 1 {print $2; exit}'
}

write_k3s_config() {
  mkdir -p /etc/rancher/k3s

  cat > /etc/rancher/k3s/config.yaml <<EOF
node-ip: ${NODE_IP}
node-name: ${NODE_NAME}
EOF

  if [[ -n "${FLANNEL_IFACE}" ]]; then
    cat >> /etc/rancher/k3s/config.yaml <<EOF
flannel-iface: ${FLANNEL_IFACE}
EOF
  fi
}

configure_ufw() {
  if ! command -v ufw >/dev/null 2>&1; then
    echo "ufw not installed, skipping firewall rules."
    return
  fi

  ufw allow 22/tcp
  ufw allow 80/tcp
  ufw allow 8472/udp
  ufw allow 9100/udp
  ufw allow 9100/tcp
  ufw allow 10250/tcp

  if [[ "${ALLOW_HTTPS}" == "true" ]]; then
    ufw allow 443/tcp
  fi
}

install_k3s_agent() {
  curl -sfL "${K3S_INSTALL_SCRIPT_URL}" | \
    INSTALL_K3S_CHANNEL="${K3S_CHANNEL}" \
    K3S_URL="${K3S_URL}" \
    K3S_TOKEN="${K3S_TOKEN}" \
    INSTALL_K3S_EXEC="agent" \
    sh -
}

print_summary() {
  echo "k3s worker bootstrap completed."
  echo "  node-name: ${NODE_NAME}"
  echo "  node-ip: ${NODE_IP}"
  if [[ -n "${FLANNEL_IFACE}" ]]; then
    echo "  flannel-iface: ${FLANNEL_IFACE}"
  else
    echo "  flannel-iface: <not set>"
  fi
}

main() {
  require_root
  require_env K3S_URL
  require_env K3S_TOKEN

  K3S_CHANNEL="${K3S_CHANNEL:-stable}"
  K3S_INSTALL_SCRIPT_URL="${K3S_INSTALL_SCRIPT_URL:-https://get.k3s.io}"
  ALLOW_HTTPS="${ALLOW_HTTPS:-false}"
  NODE_NAME="${NODE_NAME:-$(hostname -s)}"
  NODE_IP="${NODE_IP:-}"
  FLANNEL_IFACE="${FLANNEL_IFACE:-}"

  if [[ -z "${NODE_IP}" && -n "${FLANNEL_IFACE}" ]]; then
    NODE_IP="$(derive_node_ip_from_iface "${FLANNEL_IFACE}")"
  fi

  if [[ -z "${FLANNEL_IFACE}" && -n "${NODE_IP}" ]]; then
    FLANNEL_IFACE="$(derive_iface_from_node_ip "${NODE_IP}")"
  fi

  if [[ -z "${NODE_IP}" ]]; then
    echo "Unable to determine NODE_IP. Set NODE_IP explicitly or provide FLANNEL_IFACE." >&2
    exit 1
  fi

  if [[ -z "${FLANNEL_IFACE}" ]]; then
    echo "Unable to determine FLANNEL_IFACE. Set FLANNEL_IFACE explicitly." >&2
    exit 1
  fi

  configure_ufw
  write_k3s_config
  install_k3s_agent
  systemctl enable --now k3s-agent
  systemctl restart k3s-agent
  print_summary
}

main "$@"
