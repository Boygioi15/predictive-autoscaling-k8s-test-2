#!/usr/bin/env bash

set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  VULTR_API_KEY=... \
  ./linux-script/destroy-cluster-base.sh [cluster-prefix]

What it destroys:
  - all current Kubernetes worker nodes in the cluster
  - the cluster load balancer
  - the load generator VM

What it keeps:
  - the k3s master VM you are running this script on

Lookup order:
  1. Vultr object labels:
     - <prefix>-lb
     - <prefix>-loadgen
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

api_delete_with_status() {
  local path="$1"
  local response_file
  local http_code

  response_file="$(mktemp)"
  http_code="$(curl -sS -o "${response_file}" -w "%{http_code}" "${VULTR_API_BASE}${path}" \
    -X DELETE \
    -H "Authorization: Bearer ${VULTR_API_KEY}")"

  DELETE_RESPONSE_BODY="$(cat "${response_file}")"
  DELETE_RESPONSE_HTTP_CODE="${http_code}"
  rm -f "${response_file}"
}

api_get_with_status() {
  local path="$1"
  local response_file
  local http_code

  response_file="$(mktemp)"
  http_code="$(curl -sS -o "${response_file}" -w "%{http_code}" "${VULTR_API_BASE}${path}" \
    -X GET \
    -H "Authorization: Bearer ${VULTR_API_KEY}")"

  GET_RESPONSE_BODY="$(cat "${response_file}")"
  GET_RESPONSE_HTTP_CODE="${http_code}"
  rm -f "${response_file}"
}

derive_cluster_prefix() {
  local arg_prefix="${1:-}"
  local host_name

  if [[ -n "${arg_prefix}" ]]; then
    printf '%s\n' "${arg_prefix}"
    return
  fi

  if [[ -n "${CLUSTER_PREFIX:-}" ]]; then
    printf '%s\n' "${CLUSTER_PREFIX}"
    return
  fi

  host_name="$(hostname -s)"
  if [[ "${host_name}" == *-master ]]; then
    printf '%s\n' "${host_name%-master}"
    return
  fi

  echo "Unable to derive cluster prefix from hostname ${host_name}. Pass it explicitly." >&2
  exit 1
}

list_worker_nodes() {
  kubectl get nodes -o json | python3 - "$CURRENT_MASTER_NODE" <<'PY'
import json
import sys

current_master = sys.argv[1]
data = json.load(sys.stdin)

for item in data.get("items", []):
    metadata = item.get("metadata", {})
    labels = metadata.get("labels", {})
    name = metadata.get("name", "")

    if name == current_master:
      continue

    if (
        "node-role.kubernetes.io/control-plane" in labels
        or "node-role.kubernetes.io/master" in labels
    ):
        continue

    print(name)
PY
}

parse_instance_id_by_label() {
  python3 - "$1" <<'PY'
import json
import sys

target_label = sys.argv[1]
data = json.load(sys.stdin)

instances = data.get("instances", [])
matches = [instance for instance in instances if instance.get("label") == target_label]

if not matches:
    raise SystemExit(1)

if len(matches) > 1:
    raise SystemExit(f"Multiple Vultr instances matched label {target_label}")

print(matches[0].get("id", ""))
PY
}

parse_lb_id_by_label() {
  python3 - "$1" <<'PY'
import json
import sys

target_label = sys.argv[1]
data = json.load(sys.stdin)

lbs = data.get("load_balancers", [])
matches = [lb for lb in lbs if lb.get("label") == target_label]

if not matches:
    raise SystemExit(1)

if len(matches) > 1:
    raise SystemExit(f"Multiple load balancers matched label {target_label}")

print(matches[0].get("id", ""))
PY
}

parse_instance_id_by_node_name() {
  python3 - "$1" <<'PY'
import json
import sys

target_node_name = sys.argv[1]
data = json.load(sys.stdin)

matches = []
for instance in data.get("instances", []):
    label = instance.get("label", "")
    hostname = instance.get("hostname", "")
    if label == target_node_name or hostname == target_node_name:
        matches.append(instance)

if not matches:
    raise SystemExit(1)

if len(matches) > 1:
    raise SystemExit(f"Multiple Vultr instances matched node name {target_node_name}")

print(matches[0].get("id", ""))
PY
}

resolve_load_balancer_id() {
  local prefix="$1"
  local lb_id=""
  local lb_label="${prefix}-lb"
  local lbs_response

  lbs_response="$(api_call GET "/load-balancers")"
  if lb_id="$(printf '%s' "${lbs_response}" | parse_lb_id_by_label "${lb_label}" 2>/dev/null)"; then
    printf '%s\n' "${lb_id}"
    return
  fi

  printf '\n'
}

resolve_instance_id_by_role() {
  local prefix="$1"
  local role="$2"
  local instance_id=""
  local label="${prefix}-${role}"
  local instances_response

  instances_response="$(api_call GET "/instances?per_page=500")"
  if instance_id="$(printf '%s' "${instances_response}" | parse_instance_id_by_label "${label}" 2>/dev/null)"; then
    printf '%s\n' "${instance_id}"
    return
  fi

  printf '\n'
}

drain_and_delete_k8s_node() {
  local node_name="$1"

  if ! kubectl get node "${node_name}" >/dev/null 2>&1; then
    echo "Kubernetes node ${node_name} is already absent."
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

resolve_instance_id_by_node_name() {
  local node_name="$1"
  local instances_response
  local instance_id=""

  instances_response="$(api_call GET "/instances?per_page=500")"
  if instance_id="$(printf '%s' "${instances_response}" | parse_instance_id_by_node_name "${node_name}" 2>/dev/null)"; then
    printf '%s\n' "${instance_id}"
    return
  fi

  printf '\n'
}

destroy_worker_without_lb() {
  local node_name="$1"
  local instance_id

  drain_and_delete_k8s_node "${node_name}"
  instance_id="$(resolve_instance_id_by_node_name "${node_name}")"

  if [[ -z "${instance_id}" ]]; then
    echo "No Vultr instance found for worker ${node_name}, skipping VM deletion."
    return
  fi

  destroy_instance_by_id "${instance_id}"
}

wait_for_instance_absence() {
  local target_instance_id="$1"
  local deadline=$((SECONDS + WAIT_TIMEOUT_SECONDS))
  local instances_response

  while (( SECONDS < deadline )); do
    instances_response="$(api_call GET "/instances?per_page=500")"

    if ! python3 -c '
import json
import sys

target = sys.argv[1]
data = json.load(sys.stdin)

for instance in data.get("instances", []):
    if instance.get("id") == target:
        raise SystemExit(1)
' "$target_instance_id" <<<"${instances_response}"
    then
      echo "Instance ${target_instance_id} still present..."
      sleep "${WAIT_INTERVAL_SECONDS}"
      continue
    fi

    echo "Instance ${target_instance_id} is absent."
    return
  done

  echo "Timed out waiting for instance ${target_instance_id} to disappear." >&2
  exit 1
}

wait_for_lb_absence() {
  local target_lb_id="$1"
  local deadline=$((SECONDS + WAIT_TIMEOUT_SECONDS))

  while (( SECONDS < deadline )); do
    api_get_with_status "/load-balancers/${target_lb_id}"
    if [[ "${GET_RESPONSE_HTTP_CODE}" == "404" ]]; then
      echo "Load balancer ${target_lb_id} is absent."
      return
    fi

    if [[ "${GET_RESPONSE_HTTP_CODE}" =~ ^2 ]]; then
      echo "Load balancer ${target_lb_id} still present..."
      sleep "${WAIT_INTERVAL_SECONDS}"
      continue
    fi

    echo "Unexpected response while checking load balancer ${target_lb_id}:" >&2
    echo "  http_status: ${GET_RESPONSE_HTTP_CODE}" >&2
    echo "  response_body: ${GET_RESPONSE_BODY}" >&2
    exit 1
  done

  echo "Timed out waiting for load balancer ${target_lb_id} to disappear." >&2
  exit 1
}

destroy_instance_by_id() {
  local instance_id="$1"

  if [[ -z "${instance_id}" ]]; then
    return
  fi

  echo "Destroying instance ${instance_id}..."
  api_delete_with_status "/instances/${instance_id}"

  case "${DELETE_RESPONSE_HTTP_CODE}" in
    2*|404)
      ;;
    *)
      echo "Failed to destroy instance ${instance_id}." >&2
      echo "  http_status: ${DELETE_RESPONSE_HTTP_CODE}" >&2
      echo "  response_body: ${DELETE_RESPONSE_BODY}" >&2
      exit 1
      ;;
  esac

  wait_for_instance_absence "${instance_id}"
}

destroy_load_balancer_by_id() {
  local lb_id="$1"
  local deadline=$((SECONDS + WAIT_TIMEOUT_SECONDS))

  if [[ -z "${lb_id}" ]]; then
    return
  fi

  echo "Destroying load balancer ${lb_id}..."
  while (( SECONDS < deadline )); do
    api_delete_with_status "/load-balancers/${lb_id}"

    case "${DELETE_RESPONSE_HTTP_CODE}" in
      2*|404)
        wait_for_lb_absence "${lb_id}"
        return
        ;;
      400|409)
        if printf '%s' "${DELETE_RESPONSE_BODY}" | rg -q "not ready|Load balancer is not ready"; then
          echo "Load balancer ${lb_id} is not ready to delete yet, retrying..."
          sleep "${WAIT_INTERVAL_SECONDS}"
          continue
        fi
        ;;
    esac

    echo "Failed to destroy load balancer ${lb_id}." >&2
    echo "  http_status: ${DELETE_RESPONSE_HTTP_CODE}" >&2
    echo "  response_body: ${DELETE_RESPONSE_BODY}" >&2
    exit 1
  done

  echo "Timed out waiting for load balancer ${lb_id} to become deletable." >&2
  exit 1
}

destroy_workers() {
  local load_balancer_id="$1"
  local worker_nodes=()

  mapfile -t worker_nodes < <(list_worker_nodes)

  if (( ${#worker_nodes[@]} == 0 )); then
    echo "No worker nodes found in the current cluster."
    return
  fi

  echo "Worker nodes to destroy:"
  printf '  %s\n' "${worker_nodes[@]}"

  local node_name
  for node_name in "${worker_nodes[@]}"; do
    echo
    echo "Tearing down worker ${node_name}..."
    if [[ -n "${load_balancer_id}" ]]; then
      "${PROJECT_DIR}/linux-script/teardown-vultr-worker.sh" "${node_name}" "${load_balancer_id}"
    else
      echo "Load balancer id not found, falling back to direct worker teardown."
      destroy_worker_without_lb "${node_name}"
    fi
  done
}

main() {
  if [[ $# -gt 1 ]]; then
    usage
    exit 1
  fi

  require_command curl
  require_command kubectl
  require_command python3
  require_command rg
  require_env VULTR_API_KEY

  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
  VULTR_API_BASE="${VULTR_API_BASE:-https://api.vultr.com/v2}"
  WAIT_TIMEOUT_SECONDS="${WAIT_TIMEOUT_SECONDS:-300}"
  WAIT_INTERVAL_SECONDS="${WAIT_INTERVAL_SECONDS:-5}"
  KUBECTL_DRAIN_TIMEOUT="${KUBECTL_DRAIN_TIMEOUT:-5m}"
  KUBECTL_GRACE_PERIOD="${KUBECTL_GRACE_PERIOD:-30}"
  CURRENT_MASTER_NODE="${MASTER_NODE_NAME:-$(hostname -s)}"
  CLUSTER_PREFIX_RESOLVED="$(derive_cluster_prefix "${1:-}")"

  local load_balancer_id
  local load_generator_id

  echo "Destroying cluster resources for prefix ${CLUSTER_PREFIX_RESOLVED}..."
  echo "  current-master-node: ${CURRENT_MASTER_NODE}"

  load_balancer_id="$(resolve_load_balancer_id "${CLUSTER_PREFIX_RESOLVED}")"
  load_generator_id="$(resolve_instance_id_by_role "${CLUSTER_PREFIX_RESOLVED}" "loadgen")"

  echo "Resolved shared resources:"
  echo "  load-balancer-id: ${load_balancer_id:-<not found>}"
  echo "  load-generator-id: ${load_generator_id:-<not found>}"

  echo
  echo "Step 1/3: destroy all worker nodes"
  destroy_workers "${load_balancer_id}"

  echo
  echo "Step 2/3: destroy load balancer"
  if [[ -n "${load_balancer_id}" ]]; then
    destroy_load_balancer_by_id "${load_balancer_id}"
  else
    echo "No load balancer id found for prefix ${CLUSTER_PREFIX_RESOLVED}, skipping."
  fi

  echo
  echo "Step 3/3: destroy load generator"
  if [[ -n "${load_generator_id}" ]]; then
    destroy_instance_by_id "${load_generator_id}"
  else
    echo "No load generator id found for prefix ${CLUSTER_PREFIX_RESOLVED}, skipping."
  fi

  echo
  echo "Cluster destroy completed."
  echo "  prefix: ${CLUSTER_PREFIX_RESOLVED}"
  echo "  master-kept: ${CURRENT_MASTER_NODE}"
}

main "$@"
