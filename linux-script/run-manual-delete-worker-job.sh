#!/usr/bin/env bash

set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  ./linux-script/run-manual-delete-worker-job.sh <job-name> <node-name>

Example:
  ./linux-script/run-manual-delete-worker-job.sh manual-delete-1 k3s-worker-7

Notes:
  - Assumes the vm-job ConfigMap and Secret already exist.
  - `VULTR_LOAD_BALANCER_ID` is expected to come from the vm-job ConfigMap.
  - Override defaults with env vars if needed:
      VM_JOB_NAMESPACE
      VM_JOB_SERVICE_ACCOUNT
      VM_JOB_IMAGE
      VM_JOB_CONFIG_MAP
      VM_JOB_SECRET
      VM_JOB_SECRET_MOUNT_PATH
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
  if [[ $# -ne 2 ]]; then
    usage
    exit 1
  fi

  require_command kubectl

  local job_name="$1"
  local node_name="$2"
  local namespace="${VM_JOB_NAMESPACE:-custom-scaler-system}"
  local service_account="${VM_JOB_SERVICE_ACCOUNT:-custom-scaler-controller-manager}"
  local image="${VM_JOB_IMAGE:-docker.io/boygioi/vm-job:latest}"
  local config_map_name="${VM_JOB_CONFIG_MAP:-custom-scaler-vm-job-config}"
  local secret_name="${VM_JOB_SECRET:-custom-scaler-vm-job-secret}"
  local secret_mount_path="${VM_JOB_SECRET_MOUNT_PATH:-/var/run/vm-job-secret}"

  echo "Creating manual vm-job delete Job ${namespace}/${job_name} for node ${node_name}..."

  kubectl apply -f - <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: ${job_name}
  namespace: ${namespace}
spec:
  backoffLimit: 0
  ttlSecondsAfterFinished: 3600
  template:
    spec:
      serviceAccountName: ${service_account}
      restartPolicy: Never
      containers:
      - name: executor
        image: ${image}
        command:
        - /workspace/linux-script/executor-delete-worker.sh
        args:
        - ${node_name}
        envFrom:
        - configMapRef:
            name: ${config_map_name}
        env:
        - name: SCALER_NAME
          value: ${job_name}
        - name: SCALER_NAMESPACE
          value: ${namespace}
        - name: WORKER_TARGET_NODE_NAME
          value: ${node_name}
        - name: VULTR_API_KEY
          valueFrom:
            secretKeyRef:
              name: ${secret_name}
              key: VULTR_API_KEY
        - name: K3S_TOKEN
          valueFrom:
            secretKeyRef:
              name: ${secret_name}
              key: K3S_TOKEN
        volumeMounts:
        - name: vm-job-secret
          mountPath: ${secret_mount_path}
          readOnly: true
      volumes:
      - name: vm-job-secret
        secret:
          secretName: ${secret_name}
          defaultMode: 256
EOF

  echo
  echo "Manual vm-job delete job created."
  echo "Useful commands:"
  echo "  kubectl get job ${job_name} -n ${namespace}"
  echo "  kubectl get pods -n ${namespace} -l job-name=${job_name}"
  echo "  kubectl logs -f job/${job_name} -n ${namespace}"
  echo "  kubectl describe job ${job_name} -n ${namespace}"
  echo "  kubectl delete job ${job_name} -n ${namespace}"
}

main "$@"
