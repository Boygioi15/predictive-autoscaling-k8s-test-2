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

install_base_packages() {
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y \
    ca-certificates \
    curl \
    make \
    python3 \
    python3-pip \
    rsync
}

write_k3s_config() {
  mkdir -p /etc/rancher/k3s

  cat > /etc/rancher/k3s/config.yaml <<EOF
node-name: ${MASTER_NODE_NAME}
node-ip: ${NODE_IP}
advertise-address: ${ADVERTISE_ADDRESS}
write-kubeconfig-mode: "0644"
disable:
  - traefik
EOF

  if [[ -n "${FLANNEL_IFACE}" ]]; then
    cat >> /etc/rancher/k3s/config.yaml <<EOF
flannel-iface: ${FLANNEL_IFACE}
EOF
  fi

  cat >> /etc/rancher/k3s/config.yaml <<EOF
tls-san:
  - ${NODE_IP}
EOF

  if [[ -n "${MASTER_PUBLIC_IP:-}" ]]; then
    cat >> /etc/rancher/k3s/config.yaml <<EOF
  - ${MASTER_PUBLIC_IP}
EOF
  fi
}

install_k3s_server() {
  curl -sfL "${K3S_INSTALL_SCRIPT_URL}" | \
    INSTALL_K3S_CHANNEL="${K3S_CHANNEL}" \
    INSTALL_K3S_EXEC="server" \
    sh -
}

install_helm() {
  if command -v helm >/dev/null 2>&1; then
    return
  fi

  curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
}

wait_for_k3s_ready() {
  export KUBECONFIG=/etc/rancher/k3s/k3s.yaml

  systemctl enable --now k3s
  systemctl restart k3s

  echo "Waiting for the master node to register..."
  local deadline=$((SECONDS + 300))
  while (( SECONDS < deadline )); do
    if kubectl get node "${MASTER_NODE_NAME}" >/dev/null 2>&1; then
      kubectl wait --for=condition=Ready "node/${MASTER_NODE_NAME}" --timeout=300s
      return
    fi
    sleep 5
  done

  echo "Timed out waiting for node ${MASTER_NODE_NAME} to become Ready." >&2
  exit 1
}

prepare_kubeconfig() {
  mkdir -p /root/.kube
  cp /etc/rancher/k3s/k3s.yaml /root/.kube/config
  chmod 600 /root/.kube/config
}

ensure_log_dir() {
  LOG_DIR="${BOOTSTRAP_LOG_DIR:-${PROJECT_DIR}/work-log}"
  mkdir -p "${LOG_DIR}"
}

run_logged_step() {
  local step_name="$1"
  shift

  local log_file="${LOG_DIR}/${step_name}.log"
  echo "Logging ${step_name} to ${log_file}"

  if ! "$@" 2>&1 | tee "${log_file}"; then
    echo "Step ${step_name} failed. See ${log_file}" >&2
    return 1
  fi
}

collect_monitoring_debug_info() {
  local diagnostics_file="${LOG_DIR}/monitoring-install-diagnostics.log"

  {
    echo "=== Timestamp ==="
    date -Iseconds
    echo

    echo "=== Helm List ==="
    helm list -n monitoring || true
    echo

    echo "=== Helm Status ==="
    helm status monitoring-stack -n monitoring --show-resources || true
    echo

    echo "=== Helm History ==="
    helm history monitoring-stack -n monitoring || true
    echo

    echo "=== Monitoring Pods ==="
    kubectl get pods -n monitoring -o wide || true
    echo

    echo "=== Monitoring Jobs ==="
    kubectl get jobs -n monitoring -o wide || true
    echo

    echo "=== Monitoring Events ==="
    kubectl get events -n monitoring --sort-by=.lastTimestamp || true
    echo

    echo "=== Monitoring All Resources ==="
    kubectl get all -n monitoring || true
    echo

    echo "=== Monitoring PVCs ==="
    kubectl get pvc -n monitoring || true
    echo

    echo "=== PersistentVolumes ==="
    kubectl get pv || true
    echo

    echo "=== StorageClasses ==="
    kubectl get storageclass || true
    echo

    echo "=== Local Path Provisioner Pods ==="
    kubectl get pods -n kube-system -l app=local-path-provisioner -o wide || true
    echo

    echo "=== Local Path ConfigMap ==="
    kubectl get configmap local-path-config -n kube-system -o yaml || true
    echo

    echo "=== Monitoring Job Describe ==="
    for job in $(kubectl get jobs -n monitoring -o name 2>/dev/null); do
      echo "--- ${job} ---"
      kubectl describe -n monitoring "${job}" || true
      echo
    done

    echo "=== Monitoring Pod Describe ==="
    for pod in $(kubectl get pods -n monitoring -o name 2>/dev/null); do
      echo "--- ${pod} ---"
      kubectl describe -n monitoring "${pod}" || true
      echo
    done

    echo "=== Monitoring Pod Logs ==="
    for pod in $(kubectl get pods -n monitoring -o name 2>/dev/null); do
      echo "--- ${pod} ---"
      kubectl logs -n monitoring "${pod}" --all-containers=true --tail=200 || true
      echo
    done
  } > "${diagnostics_file}" 2>&1

  echo "Wrote monitoring diagnostics to ${diagnostics_file}" >&2
}

patch_local_path_provisioner_for_infra_taint() {
  echo "Patching local-path provisioner for role=infra:NoSchedule..."

  kubectl -n kube-system patch deployment local-path-provisioner --type merge -p '
spec:
  template:
    spec:
      tolerations:
        - key: role
          operator: Equal
          value: infra
          effect: NoSchedule
' >/dev/null

  kubectl -n kube-system get configmap local-path-config -o json | python3 - <<'PY' | kubectl apply -f -
import json
import sys

config = json.load(sys.stdin)
helper = config.get("data", {}).get("helperPod.yaml", "")

infra_snippet = "\n            - key: role\n              operator: Equal\n              value: infra\n              effect: NoSchedule"

if "key: role" not in helper:
    marker = "          tolerations:"
    if marker in helper:
        helper = helper.replace(marker, marker + infra_snippet, 1)
    else:
        helper = helper.replace(
            "        spec:\n",
            "        spec:\n          tolerations:\n            - key: role\n              operator: Equal\n              value: infra\n              effect: NoSchedule\n",
            1,
        )

config.setdefault("data", {})["helperPod.yaml"] = helper
json.dump(config, sys.stdout)
PY

  kubectl rollout restart deployment/local-path-provisioner -n kube-system >/dev/null
  kubectl rollout status deployment/local-path-provisioner -n kube-system --timeout=300s
}

label_and_taint_master() {
  kubectl label node "${MASTER_NODE_NAME}" role=infra --overwrite
  kubectl taint node "${MASTER_NODE_NAME}" role=infra:NoSchedule --overwrite
}

install_monitoring_stack() {
  if ! run_logged_step monitoring-install make -C "${PROJECT_DIR}" install-helm-monitor; then
    collect_monitoring_debug_info
    return 1
  fi

  run_logged_step monitoring-service-monitor make -C "${PROJECT_DIR}" deploy-monitor
}

install_ingress_stack() {
  make -C "${PROJECT_DIR}" install-helm-ingress
}

filter_custom_scaler_bundle() {
  kubectl kustomize "${PROJECT_DIR}/custom-scaler/config/default" | python3 -c '
import sys

docs = sys.stdin.read().split("\n---\n")
filtered = []
skip_names = {"custom-scaler-vm-job-config", "custom-scaler-vm-job-secret"}

for doc in docs:
    stripped = doc.strip()
    if not stripped:
        continue

    lines = stripped.splitlines()
    kind = None
    name = None
    for line in lines:
        if line.startswith("kind: "):
            kind = line.split(": ", 1)[1].strip()
        if line.startswith("  name: ") and name is None:
            name = line.split(": ", 1)[1].strip()

    if kind in {"ConfigMap", "Secret"} and name in skip_names:
        continue

    filtered.append(stripped)

if filtered:
    sys.stdout.write("\n---\n".join(filtered))
    sys.stdout.write("\n")
'
}

apply_custom_scaler_bundle() {
  local bundle_path
  bundle_path="$(mktemp)"
  trap 'rm -f "${bundle_path}"' RETURN

  filter_custom_scaler_bundle > "${bundle_path}"
  kubectl apply -f "${bundle_path}"
  kubectl -n custom-scaler-system set image deployment/custom-scaler-controller-manager "manager=${CUSTOM_SCALER_IMAGE}"
}

write_vm_job_secret_files() {
  install -d -m 700 /root/.ssh
  install -m 600 "${VM_JOB_PRIVATE_KEY_PATH}" /root/.ssh/vm-job_ed25519
  install -m 644 "${VM_JOB_PUBLIC_KEY_PATH}" /root/.ssh/vm-job_ed25519.pub
}

apply_vm_job_config() {
  local worker_k3s_url="${WORKER_K3S_URL:-https://${ADVERTISE_ADDRESS}:6443}"

  kubectl -n custom-scaler-system create configmap custom-scaler-vm-job-config \
    --from-literal=VULTR_REGION="${WORKER_VULTR_REGION}" \
    --from-literal=VULTR_PLAN="${WORKER_VULTR_PLAN}" \
    --from-literal=VULTR_OS_ID="${WORKER_VULTR_OS_ID}" \
    --from-literal=VULTR_FIREWALL_GROUP_ID="${WORKER_VULTR_FIREWALL_GROUP_ID}" \
    --from-literal=VULTR_VPC_ID="${WORKER_VULTR_VPC_ID}" \
    --from-literal=VULTR_SSH_KEY_IDS="${WORKER_VULTR_SSH_KEY_IDS}" \
    --from-literal=VULTR_LOAD_BALANCER_ID="${VULTR_LOAD_BALANCER_ID}" \
    --from-literal=VULTR_BOOTSTRAP_SSH_USER="${VULTR_BOOTSTRAP_SSH_USER}" \
    --from-literal=K3S_URL="${worker_k3s_url}" \
    --from-literal=FLANNEL_IFACE_DEFAULT="${FLANNEL_IFACE}" \
    --from-literal=BOOTSTRAP_SSH_HOST_MODE="${WORKER_BOOTSTRAP_SSH_HOST_MODE}" \
    --from-literal=VULTR_ROOT_PUBLIC_KEY_FILE="/var/run/vm-job-secret/id_ed25519.pub" \
    --from-literal=SSH_OPTS="-i /var/run/vm-job-secret/id_ed25519 -o StrictHostKeyChecking=accept-new" \
    --dry-run=client -o yaml | kubectl apply -f -
}

apply_vm_job_secret() {
  local k3s_token
  k3s_token="$(cat /var/lib/rancher/k3s/server/node-token)"

  kubectl -n custom-scaler-system create secret generic custom-scaler-vm-job-secret \
    --from-literal=VULTR_API_KEY="${VULTR_API_KEY}" \
    --from-literal=K3S_TOKEN="${k3s_token}" \
    --from-file=id_ed25519=/root/.ssh/vm-job_ed25519 \
    --from-file=id_ed25519.pub=/root/.ssh/vm-job_ed25519.pub \
    --dry-run=client -o yaml | kubectl apply -f -
}

wait_for_custom_scaler_ready() {
  kubectl wait --for=condition=Established crd/customscalers.autoscaling.my.domain --timeout=300s
  kubectl rollout status deployment/custom-scaler-controller-manager -n custom-scaler-system --timeout=300s
}

apply_custom_scaler_sample() {
  kubectl apply -f "${PROJECT_DIR}/custom-scaler/config/samples/autoscaling_v1_customscaler.yaml"
}

write_access_files() {
  local k3s_token
  local kubeconfig_private_path="${PROJECT_DIR}/shares/kubeconfig-private.yaml"
  local kubeconfig_public_path="${PROJECT_DIR}/shares/kubeconfig-public.yaml"
  local worker_env_path="${PROJECT_DIR}/shares/k3s-worker.env"

  mkdir -p "${PROJECT_DIR}/shares"

  k3s_token="$(cat /var/lib/rancher/k3s/server/node-token)"

  python3 - <<'PY' "${worker_env_path}" "${ADVERTISE_ADDRESS}" "${k3s_token}"
from pathlib import Path
import sys

path = Path(sys.argv[1])
server_ip = sys.argv[2]
token = sys.argv[3]

path.write_text(
    f"K3S_URL=https://{server_ip}:6443\nK3S_TOKEN={token}\n",
    encoding="utf-8",
)
PY

  python3 - <<'PY' /etc/rancher/k3s/k3s.yaml "${kubeconfig_private_path}" "${ADVERTISE_ADDRESS}"
from pathlib import Path
import sys

source = Path(sys.argv[1]).read_text(encoding="utf-8")
target = Path(sys.argv[2])
server_ip = sys.argv[3]

target.write_text(source.replace("https://127.0.0.1:6443", f"https://{server_ip}:6443"), encoding="utf-8")
PY

  if [[ -n "${MASTER_PUBLIC_IP:-}" ]]; then
    python3 - <<'PY' /etc/rancher/k3s/k3s.yaml "${kubeconfig_public_path}" "${MASTER_PUBLIC_IP}"
from pathlib import Path
import sys

source = Path(sys.argv[1]).read_text(encoding="utf-8")
target = Path(sys.argv[2])
server_ip = sys.argv[3]

target.write_text(source.replace("https://127.0.0.1:6443", f"https://{server_ip}:6443"), encoding="utf-8")
PY
  fi
}

print_summary() {
  echo
  echo "Master bootstrap completed."
  echo "  project-dir: ${PROJECT_DIR}"
  echo "  node-name: ${MASTER_NODE_NAME}"
  echo "  node-ip: ${NODE_IP}"
  echo "  advertise-address: ${ADVERTISE_ADDRESS}"
  echo "  flannel-iface: ${FLANNEL_IFACE}"
  echo "  monitoring: ${INSTALL_MONITORING}"
  echo "  ingress: ${INSTALL_INGRESS}"
  echo "  custom-scaler: ${DEPLOY_CUSTOM_SCALER}"
}

main() {
  require_root
  require_env MASTER_NODE_NAME
  require_env PROJECT_DIR

  PROJECT_DIR="${PROJECT_DIR%/}"
  K3S_CHANNEL="${K3S_CHANNEL:-stable}"
  K3S_INSTALL_SCRIPT_URL="${K3S_INSTALL_SCRIPT_URL:-https://get.k3s.io}"
  CUSTOM_SCALER_IMAGE="${CUSTOM_SCALER_IMAGE:-docker.io/boygioi/custom-scaler:latest}"
  INSTALL_MONITORING="${INSTALL_MONITORING:-true}"
  INSTALL_INGRESS="${INSTALL_INGRESS:-false}"
  DEPLOY_CUSTOM_SCALER="${DEPLOY_CUSTOM_SCALER:-true}"
  APPLY_CUSTOM_SCALER_SAMPLE="${APPLY_CUSTOM_SCALER_SAMPLE:-true}"
  WORKER_BOOTSTRAP_SSH_HOST_MODE="${WORKER_BOOTSTRAP_SSH_HOST_MODE:-private}"
  VULTR_BOOTSTRAP_SSH_USER="${VULTR_BOOTSTRAP_SSH_USER:-root}"
  NODE_IP="${MASTER_PRIVATE_IP:-${MASTER_PUBLIC_IP:-}}"
  ADVERTISE_ADDRESS="${MASTER_PRIVATE_IP:-${MASTER_PUBLIC_IP:-}}"
  FLANNEL_IFACE="${FLANNEL_IFACE_DEFAULT:-}"

  install_base_packages
  ensure_log_dir

  if [[ -z "${NODE_IP}" && -n "${FLANNEL_IFACE}" ]]; then
    NODE_IP="$(derive_node_ip_from_iface "${FLANNEL_IFACE}")"
    ADVERTISE_ADDRESS="${NODE_IP}"
  fi

  if [[ -z "${FLANNEL_IFACE}" && -n "${NODE_IP}" ]]; then
    FLANNEL_IFACE="$(derive_iface_from_node_ip "${NODE_IP}")"
  fi

  if [[ -z "${NODE_IP}" ]]; then
    echo "Unable to determine the master node IP." >&2
    exit 1
  fi

  if [[ -z "${FLANNEL_IFACE}" ]]; then
    echo "Unable to determine FLANNEL_IFACE. Set FLANNEL_IFACE_DEFAULT explicitly." >&2
    exit 1
  fi

  write_k3s_config
  install_k3s_server
  wait_for_k3s_ready
  prepare_kubeconfig
  install_helm
  label_and_taint_master
  patch_local_path_provisioner_for_infra_taint

  if [[ "${INSTALL_MONITORING}" == "true" ]]; then
    install_monitoring_stack
  fi

  if [[ "${INSTALL_INGRESS}" == "true" ]]; then
    install_ingress_stack
  fi

  if [[ "${DEPLOY_CUSTOM_SCALER}" == "true" ]]; then
    require_env WORKER_VULTR_REGION
    require_env WORKER_VULTR_PLAN
    require_env WORKER_VULTR_OS_ID
    require_env VULTR_LOAD_BALANCER_ID
    require_env VULTR_API_KEY
    require_env VM_JOB_PRIVATE_KEY_PATH
    require_env VM_JOB_PUBLIC_KEY_PATH

    apply_custom_scaler_bundle
    write_vm_job_secret_files
    apply_vm_job_config
    apply_vm_job_secret
    wait_for_custom_scaler_ready

    if [[ "${APPLY_CUSTOM_SCALER_SAMPLE}" == "true" ]]; then
      apply_custom_scaler_sample
    fi
  fi

  write_access_files
  print_summary
}

main "$@"
