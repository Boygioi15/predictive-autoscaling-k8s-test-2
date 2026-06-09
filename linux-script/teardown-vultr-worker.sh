#!/usr/bin/env bash

set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  VULTR_API_KEY=... \
  ./linux-script/teardown-vultr-worker.sh <k8s-node-name> <load-balancer-id> <vm-public-ip>

Example:
  VULTR_API_KEY=... \
  ./linux-script/teardown-vultr-worker.sh worker-5 abcd1234 149.28.132.166
EOF
}

require_env() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    echo "Missing required environment variable: ${name}" >&2
    exit 1
  fi
}

require_command() {
  local name="$1"
  if ! command -v "${name}" >/dev/null 2>&1; then
    echo "Missing required command: ${name}" >&2
    exit 1
  fi
}

api_call() {
  local method="$1"
  local path="$2"
  local body="${3:-}"
  local expect_body="${4:-true}"
  local response_file
  local http_code

  response_file="$(mktemp)"

  if [[ -n "${body}" ]]; then
    http_code="$(curl -sS -o "${response_file}" -w "%{http_code}" "${VULTR_API_BASE}${path}" \
      -X "${method}" \
      -H "Authorization: Bearer ${VULTR_API_KEY}" \
      -H "Content-Type: application/json" \
      --data "${body}")"
  else
    http_code="$(curl -sS -o "${response_file}" -w "%{http_code}" "${VULTR_API_BASE}${path}" \
      -X "${method}" \
      -H "Authorization: Bearer ${VULTR_API_KEY}")"
  fi

  if [[ ! "${http_code}" =~ ^2 ]]; then
    echo "Vultr API request failed." >&2
    echo "  method: ${method}" >&2
    echo "  path: ${path}" >&2
    echo "  http_status: ${http_code}" >&2
    echo "  response_body:" >&2
    sed 's/^/    /' "${response_file}" >&2 || true
    rm -f "${response_file}"
    exit 1
  fi

  if [[ "${expect_body}" == "false" ]]; then
    rm -f "${response_file}"
    return 0
  fi

  if [[ ! -s "${response_file}" ]]; then
    echo "Vultr API returned an empty response body." >&2
    echo "  method: ${method}" >&2
    echo "  path: ${path}" >&2
    echo "  http_status: ${http_code}" >&2
    rm -f "${response_file}"
    exit 1
  fi

  cat "${response_file}"
  rm -f "${response_file}"
}

parse_instance_id_by_public_ip() {
  python3 -c '
import json
import sys

target_public_ip = sys.argv[1]
data = json.load(sys.stdin)

for instance in data.get("instances", []):
    if instance.get("main_ip") == target_public_ip:
        print(instance["id"])
        sys.exit(0)

raise SystemExit(f"No Vultr instance found with public IP: {target_public_ip}")
' "$TARGET_PUBLIC_IP"
}

instance_exists_in_list() {
  local instances_response="$1"
  local target_instance_id="$2"

  python3 -c '
import json
import sys

target_instance_id = sys.argv[1]
data = json.load(sys.stdin)

for instance in data.get("instances", []):
    if instance.get("id") == target_instance_id:
        sys.exit(0)

sys.exit(1)
' "$target_instance_id" <<<"${instances_response}"
}

parse_lb_summary() {
  python3 -c '
import json
import sys

data = json.load(sys.stdin)
lb = data.get("load_balancer", {})

print(lb.get("id", ""))
print(lb.get("label", ""))
print(lb.get("region", ""))
print(lb.get("status", ""))
for instance_id in lb.get("instances", []):
    print(instance_id)
'
}

build_detach_payload() {
  python3 -c '
import json
import sys

target_instance_id = sys.argv[1]
data = json.load(sys.stdin)
lb = data.get("load_balancer", {})

remaining_instances = [
    instance_id
    for instance_id in lb.get("instances", [])
    if instance_id and instance_id != target_instance_id
]

print(json.dumps({"instances": remaining_instances}))
' "$TARGET_INSTANCE_ID"
}

lb_has_instance() {
  local lb_response="$1"
  local target_instance_id="$2"

  python3 -c '
import json
import sys

target_instance_id = sys.argv[1]
data = json.load(sys.stdin)
lb = data.get("load_balancer", {})
instances = lb.get("instances", [])

sys.exit(0 if target_instance_id in instances else 1)
' "$target_instance_id" <<<"${lb_response}"
}

node_exists() {
  local node_name="$1"
  kubectl get node "${node_name}" >/dev/null 2>&1
}

detach_node_from_cluster() {
  local node_name="$1"

  if ! node_exists "${node_name}"; then
    echo "Kubernetes node ${node_name} is already absent, skipping cluster detach."
    return
  fi

  echo "Cordoning node ${node_name}..."
  kubectl cordon "${node_name}" >/dev/null 2>&1 || true

  echo "Draining node ${node_name}..."
  kubectl drain "${node_name}" \
    --ignore-daemonsets \
    --delete-emptydir-data \
    --force \
    --timeout="${KUBECTL_DRAIN_TIMEOUT}" \
    --grace-period="${KUBECTL_GRACE_PERIOD}"

  echo "Deleting node ${node_name} from the cluster..."
  kubectl delete node "${node_name}"
}

get_deployment_replicas() {
  local namespace="$1"
  local deployment="$2"

  kubectl get deployment "${deployment}" -n "${namespace}" -o jsonpath='{.spec.replicas}'
}

scale_down_ingress() {
  local namespace="$1"
  local deployment="$2"
  local decrement="$3"
  local min_replicas="$4"

  echo "Scaling down ingress deployment ${namespace}/${deployment}..."

  local current_replicas
  current_replicas="$(get_deployment_replicas "${namespace}" "${deployment}")"

  if [[ -z "${current_replicas}" ]]; then
    echo "Unable to read current ingress replicas for ${namespace}/${deployment}." >&2
    exit 1
  fi

  local desired_replicas=$(( current_replicas - decrement ))
  if (( desired_replicas < min_replicas )); then
    desired_replicas="${min_replicas}"
  fi

  echo "  current-replicas=${current_replicas}"
  echo "  desired-replicas=${desired_replicas}"

  kubectl scale deployment "${deployment}" -n "${namespace}" --replicas="${desired_replicas}"
  kubectl rollout status deployment "${deployment}" -n "${namespace}" --timeout="${KUBECTL_ROLLOUT_TIMEOUT}"
}

detach_vm_from_lb() {
  local lb_response
  local patch_payload
  local deadline
  local lb_status

  echo "Fetching current load balancer state for ${TARGET_LOAD_BALANCER_ID}..."
  lb_response="$(api_call GET "/load-balancers/${TARGET_LOAD_BALANCER_ID}")"

  if ! lb_has_instance "${lb_response}" "${TARGET_INSTANCE_ID}"; then
    echo "Instance ${TARGET_INSTANCE_ID} is already absent from load balancer ${TARGET_LOAD_BALANCER_ID}."
    return
  fi

  patch_payload="$(printf '%s' "${lb_response}" | build_detach_payload)"

  echo "Detaching instance ${TARGET_INSTANCE_ID} from load balancer ${TARGET_LOAD_BALANCER_ID}..."
  api_call PATCH "/load-balancers/${TARGET_LOAD_BALANCER_ID}" "${patch_payload}" false >/dev/null

  deadline=$((SECONDS + WAIT_TIMEOUT_SECONDS))
  while (( SECONDS < deadline )); do
    lb_response="$(api_call GET "/load-balancers/${TARGET_LOAD_BALANCER_ID}")"
    mapfile -t lb_summary < <(printf '%s' "${lb_response}" | parse_lb_summary)
    lb_status="${lb_summary[3]}"

    if ! lb_has_instance "${lb_response}" "${TARGET_INSTANCE_ID}"; then
      echo "Instance ${TARGET_INSTANCE_ID} is no longer attached to load balancer ${TARGET_LOAD_BALANCER_ID}."
      return
    fi

    echo "  lb-status=${lb_status:-<unknown>} target-instance-still-attached=true"
    sleep "${WAIT_INTERVAL_SECONDS}"
  done

  echo "Timed out waiting for load balancer ${TARGET_LOAD_BALANCER_ID} to detach instance ${TARGET_INSTANCE_ID}." >&2
  exit 1
}

destroy_instance() {
  echo "Destroying Vultr instance ${TARGET_INSTANCE_ID}..."
  api_call DELETE "/instances/${TARGET_INSTANCE_ID}" "" false >/dev/null

  local deadline
  local instances_response

  deadline=$((SECONDS + WAIT_TIMEOUT_SECONDS))
  while (( SECONDS < deadline )); do
    instances_response="$(api_call GET "/instances?per_page=500")"

    if ! instance_exists_in_list "${instances_response}" "${TARGET_INSTANCE_ID}"; then
      echo "Instance ${TARGET_INSTANCE_ID} is gone from the Vultr instance list."
      return
    fi

    echo "  target-instance-still-present=true"
    sleep "${WAIT_INTERVAL_SECONDS}"
  done

  echo "Timed out waiting for instance ${TARGET_INSTANCE_ID} to disappear from the Vultr instance list." >&2
  exit 1
}

main() {
  if [[ $# -ne 3 ]]; then
    usage
    exit 1
  fi

  require_command curl
  require_command kubectl
  require_command python3
  require_env VULTR_API_KEY

  TARGET_NODE_NAME="$1"
  TARGET_LOAD_BALANCER_ID="$2"
  TARGET_PUBLIC_IP="$3"

  VULTR_API_BASE="${VULTR_API_BASE:-https://api.vultr.com/v2}"
  WAIT_TIMEOUT_SECONDS="${WAIT_TIMEOUT_SECONDS:-300}"
  WAIT_INTERVAL_SECONDS="${WAIT_INTERVAL_SECONDS:-5}"
  KUBECTL_DRAIN_TIMEOUT="${KUBECTL_DRAIN_TIMEOUT:-5m}"
  KUBECTL_ROLLOUT_TIMEOUT="${KUBECTL_ROLLOUT_TIMEOUT:-180s}"
  KUBECTL_GRACE_PERIOD="${KUBECTL_GRACE_PERIOD:-30}"
  INGRESS_NAMESPACE="${INGRESS_NAMESPACE:-ingress-nginx}"
  INGRESS_DEPLOYMENT="${INGRESS_DEPLOYMENT:-ingress-nginx-controller}"
  INGRESS_REPLICA_DECREMENT="${INGRESS_REPLICA_DECREMENT:-2}"
  INGRESS_MIN_REPLICAS="${INGRESS_MIN_REPLICAS:-1}"

  local instances_response

  echo "Resolving Vultr instance for public IP ${TARGET_PUBLIC_IP}..."
  instances_response="$(api_call GET "/instances?per_page=500")"
  TARGET_INSTANCE_ID="$(printf '%s' "${instances_response}" | parse_instance_id_by_public_ip)"
  echo "Resolved instance-id: ${TARGET_INSTANCE_ID}"

  echo
  echo "Step 1/4: detach node from Kubernetes"
  detach_node_from_cluster "${TARGET_NODE_NAME}"

  echo
  echo "Step 2/4: scale down ingress"
  scale_down_ingress "${INGRESS_NAMESPACE}" "${INGRESS_DEPLOYMENT}" "${INGRESS_REPLICA_DECREMENT}" "${INGRESS_MIN_REPLICAS}"

  echo
  echo "Step 3/4: detach VM from load balancer"
  detach_vm_from_lb

  echo
  echo "Step 4/4: destroy Vultr VM"
  destroy_instance

  echo
  echo "Teardown completed:"
  echo "  node-name: ${TARGET_NODE_NAME}"
  echo "  load-balancer-id: ${TARGET_LOAD_BALANCER_ID}"
  echo "  public-ip: ${TARGET_PUBLIC_IP}"
  echo "  instance-id: ${TARGET_INSTANCE_ID}"
}

main "$@"
