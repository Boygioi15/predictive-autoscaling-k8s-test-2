#!/usr/bin/env bash

set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  VULTR_API_KEY=... \
  ./linux-script/teardown-vultr-worker.sh <k8s-node-name> <load-balancer-id>

Example:
  VULTR_API_KEY=... \
  ./linux-script/teardown-vultr-worker.sh worker-5 abcd1234
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

debug_log_response() {
  local label="$1"
  local response="$2"

  if [[ "${DEBUG_VULTR_INSTANCE_LOOKUP:-false}" != "true" ]]; then
    return
  fi

  echo "DEBUG ${label} response begin" >&2
  printf '%s\n' "${response}" >&2
  echo "DEBUG ${label} response end" >&2
}

debug_log_instance_match() {
  if [[ "${DEBUG_VULTR_INSTANCE_LOOKUP:-false}" != "true" ]]; then
    return
  fi

  echo "DEBUG parsed instance_match count=${#instance_match[@]}" >&2
  local idx
  for idx in "${!instance_match[@]}"; do
    echo "DEBUG instance_match[${idx}]=${instance_match[$idx]}" >&2
  done
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

parse_instance_by_node_name() {
  python3 -c '
import json
import sys

target_node_name = sys.argv[1]
label_prefix = sys.argv[2]
hostname_prefix = sys.argv[3]
data = json.load(sys.stdin)

if isinstance(data, dict) and "instances" in data and isinstance(data.get("instances"), list):
    instances = data.get("instances", [])
elif isinstance(data, dict):
    instances = [data]
elif isinstance(data, list):
    instances = data
else:
    raise SystemExit(f"Unsupported Vultr instance response shape: {type(data).__name__}")

candidates = []
expected_labels = {target_node_name, f"{label_prefix}{target_node_name}" if label_prefix else target_node_name}
expected_hostnames = {target_node_name, f"{hostname_prefix}{target_node_name}" if hostname_prefix else target_node_name}

for instance in instances:
    if not isinstance(instance, dict):
        continue
    label = instance.get("label", "")
    hostname = instance.get("hostname", "")
    if label in expected_labels or hostname in expected_hostnames:
        candidates.append(instance)

if not candidates:
    raise SystemExit(f"No Vultr instance found for node name: {target_node_name}")

if len(candidates) > 1:
    lines = [f"Multiple Vultr instances matched node name: {target_node_name}"]
    for instance in candidates:
        lines.append(
            "  id={id} label={label} hostname={hostname} public_ip={public_ip}".format(
                id=instance.get("id"),
                label=instance.get("label", ""),
                hostname=instance.get("hostname", ""),
                public_ip=instance.get("main_ip", ""),
            )
        )
    raise SystemExit("\n".join(lines))

instance = candidates[0]
print(instance.get("id", ""))
print(instance.get("label", ""))
print(instance.get("hostname", ""))
print(instance.get("main_ip", ""))
' "$TARGET_NODE_NAME" "${VULTR_LABEL_PREFIX:-}" "${VULTR_HOSTNAME_PREFIX:-}"
}

wait_for_instance_resolution_by_node_name() {
  local deadline=$((SECONDS + WAIT_TIMEOUT_SECONDS))
  local attempt=1
  local instances_response

  while (( SECONDS < deadline )); do
    instances_response="$(api_call GET "/instances?per_page=500")"
    debug_log_response "GET /instances?per_page=500" "${instances_response}"
    if mapfile -t instance_match < <(printf '%s' "${instances_response}" | parse_instance_by_node_name 2>/dev/null); then
      debug_log_instance_match
      if (( ${#instance_match[@]} >= 4 )); then
        RESOLVED_INSTANCES_RESPONSE="${instances_response}"
        return 0
      fi
    fi

    echo "  Instance for node name ${TARGET_NODE_NAME} is not visible yet (attempt ${attempt}), retrying in ${WAIT_INTERVAL_SECONDS}s..."
    attempt=$((attempt + 1))
    sleep "${WAIT_INTERVAL_SECONDS}"
  done

  echo "Timed out waiting for Vultr instance for node name ${TARGET_NODE_NAME} to appear in the instance list." >&2
  instances_response="$(api_call GET "/instances?per_page=500")"
  debug_log_response "GET /instances?per_page=500" "${instances_response}"
  mapfile -t instance_match < <(printf '%s' "${instances_response}" | parse_instance_by_node_name)
  debug_log_instance_match
  if (( ${#instance_match[@]} < 4 )); then
    echo "Resolved instance data for node name ${TARGET_NODE_NAME} was incomplete." >&2
    exit 1
  fi
  RESOLVED_INSTANCES_RESPONSE="${instances_response}"
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
  if [[ $# -ne 2 ]]; then
    usage
    exit 1
  fi

  require_command curl
  require_command kubectl
  require_command python3
  require_env VULTR_API_KEY

  TARGET_NODE_NAME="$1"
  TARGET_LOAD_BALANCER_ID="$2"

  VULTR_API_BASE="${VULTR_API_BASE:-https://api.vultr.com/v2}"
  WAIT_TIMEOUT_SECONDS="${WAIT_TIMEOUT_SECONDS:-300}"
  WAIT_INTERVAL_SECONDS="${WAIT_INTERVAL_SECONDS:-5}"
  KUBECTL_DRAIN_TIMEOUT="${KUBECTL_DRAIN_TIMEOUT:-5m}"
  KUBECTL_GRACE_PERIOD="${KUBECTL_GRACE_PERIOD:-30}"

  local instances_response
  local instance_label
  local instance_hostname
  local -a instance_match=()

  echo "Resolving Vultr instance for node name ${TARGET_NODE_NAME}..."
  wait_for_instance_resolution_by_node_name
  instances_response="${RESOLVED_INSTANCES_RESPONSE}"
  if (( ${#instance_match[@]} < 4 )); then
    echo "Failed to resolve a complete Vultr instance record for node name ${TARGET_NODE_NAME}." >&2
    exit 1
  fi
  TARGET_INSTANCE_ID="${instance_match[0]}"
  instance_label="${instance_match[1]}"
  instance_hostname="${instance_match[2]}"
  TARGET_PUBLIC_IP="${instance_match[3]}"

  echo "Resolved Vultr instance:"
  echo "  instance-id: ${TARGET_INSTANCE_ID}"
  echo "  label: ${instance_label:-<none>}"
  echo "  hostname: ${instance_hostname:-<none>}"
  echo "  public-ip: ${TARGET_PUBLIC_IP:-<none>}"

  echo
  echo "Step 1/3: detach node from Kubernetes"
  detach_node_from_cluster "${TARGET_NODE_NAME}"

  echo
  echo "Step 2/3: detach VM from load balancer"
  detach_vm_from_lb

  echo
  echo "Step 3/3: destroy Vultr VM"
  destroy_instance

  echo
  echo "Teardown completed:"
  echo "  node-name: ${TARGET_NODE_NAME}"
  echo "  load-balancer-id: ${TARGET_LOAD_BALANCER_ID}"
  echo "  public-ip: ${TARGET_PUBLIC_IP}"
  echo "  instance-id: ${TARGET_INSTANCE_ID}"
}

main "$@"
