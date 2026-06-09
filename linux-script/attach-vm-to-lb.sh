#!/usr/bin/env bash

set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  VULTR_API_KEY=... \
  ./linux-script/attach-vm-to-lb.sh <load-balancer-id> <vm-public-ip>

Example:
  VULTR_API_KEY=... \
  ./linux-script/attach-vm-to-lb.sh abcd1234 149.28.132.166
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

instances = data.get("instances", [])
for instance in instances:
    if instance.get("main_ip") == target_public_ip:
        print(instance["id"])
        sys.exit(0)

raise SystemExit(f"No Vultr instance found with public IP: {target_public_ip}")
' "$TARGET_PUBLIC_IP"
}

parse_instance_summary() {
  python3 -c '
import json
import sys

target_instance_id = sys.argv[1]
data = json.load(sys.stdin)

instances = data.get("instances", [])
for instance in instances:
    if instance.get("id") == target_instance_id:
        print(instance.get("label", ""))
        print(instance.get("region", ""))
        print(instance.get("status", ""))
        print(instance.get("server_status", ""))
        print(instance.get("main_ip", ""))
        sys.exit(0)

raise SystemExit(f"No Vultr instance found with id: {target_instance_id}")
' "$TARGET_INSTANCE_ID"
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

build_patch_payload() {
  python3 -c '
import json
import sys

target_instance_id = sys.argv[1]
data = json.load(sys.stdin)
lb = data.get("load_balancer", {})

current_instances = lb.get("instances", [])
merged_instances = []
seen = set()

for instance_id in current_instances + [target_instance_id]:
    if not instance_id or instance_id in seen:
        continue
    merged_instances.append(instance_id)
    seen.add(instance_id)

print(json.dumps({"instances": merged_instances}))
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

print_lb_state() {
  local lb_response="$1"

  python3 -c '
import json
import sys

data = json.load(sys.stdin)
lb = data.get("load_balancer", {})

summary = {
    "id": lb.get("id"),
    "label": lb.get("label"),
    "region": lb.get("region"),
    "status": lb.get("status"),
    "ip": lb.get("ip"),
    "instances": lb.get("instances", []),
    "instance_count": len(lb.get("instances", [])),
}

print(json.dumps(summary, indent=2))
' <<<"${lb_response}"
}

main() {
  if [[ $# -ne 2 ]]; then
    usage
    exit 1
  fi

  require_command curl
  require_command python3
  require_env VULTR_API_KEY

  TARGET_LOAD_BALANCER_ID="$1"
  TARGET_PUBLIC_IP="$2"
  VULTR_API_BASE="${VULTR_API_BASE:-https://api.vultr.com/v2}"
  WAIT_TIMEOUT_SECONDS="${WAIT_TIMEOUT_SECONDS:-300}"
  WAIT_INTERVAL_SECONDS="${WAIT_INTERVAL_SECONDS:-5}"

  local instances_response
  local lb_response
  local patch_payload
  local deadline
  local lb_id
  local lb_label
  local lb_region
  local lb_status
  local current_lb_instances

  echo "Resolving Vultr instance for public IP ${TARGET_PUBLIC_IP}..."
  instances_response="$(api_call GET "/instances?per_page=500")"
  TARGET_INSTANCE_ID="$(printf '%s' "${instances_response}" | parse_instance_id_by_public_ip)"

  mapfile -t instance_summary < <(printf '%s' "${instances_response}" | parse_instance_summary)
  local instance_label="${instance_summary[0]}"
  local instance_region="${instance_summary[1]}"
  local instance_status="${instance_summary[2]}"
  local instance_server_status="${instance_summary[3]}"

  echo "Resolved instance:"
  echo "  instance-id: ${TARGET_INSTANCE_ID}"
  echo "  label: ${instance_label:-<none>}"
  echo "  region: ${instance_region:-<unknown>}"
  echo "  status: ${instance_status:-<unknown>}"
  echo "  server-status: ${instance_server_status:-<unknown>}"

  echo
  echo "Fetching current load balancer state..."
  lb_response="$(api_call GET "/load-balancers/${TARGET_LOAD_BALANCER_ID}")"
  mapfile -t lb_summary < <(printf '%s' "${lb_response}" | parse_lb_summary)
  lb_id="${lb_summary[0]}"
  lb_label="${lb_summary[1]}"
  lb_region="${lb_summary[2]}"
  lb_status="${lb_summary[3]}"
  current_lb_instances=("${lb_summary[@]:4}")

  echo "Current load balancer:"
  echo "  lb-id: ${lb_id}"
  echo "  label: ${lb_label:-<none>}"
  echo "  region: ${lb_region:-<unknown>}"
  echo "  status: ${lb_status:-<unknown>}"
  echo "  attached-instances: ${#current_lb_instances[@]}"

  if [[ "${instance_region}" != "${lb_region}" ]]; then
    echo "Instance region (${instance_region}) does not match load balancer region (${lb_region})." >&2
    exit 1
  fi

  if lb_has_instance "${lb_response}" "${TARGET_INSTANCE_ID}"; then
    echo
    echo "Instance ${TARGET_INSTANCE_ID} is already attached to load balancer ${lb_id}."
    echo "Current load balancer state:"
    print_lb_state "${lb_response}"
    return
  fi

  patch_payload="$(printf '%s' "${lb_response}" | build_patch_payload)"

  echo
  echo "Updating load balancer ${lb_id} with merged backend list..."
  api_call PATCH "/load-balancers/${TARGET_LOAD_BALANCER_ID}" "${patch_payload}" false >/dev/null

  deadline=$((SECONDS + WAIT_TIMEOUT_SECONDS))

  while (( SECONDS < deadline )); do
    lb_response="$(api_call GET "/load-balancers/${TARGET_LOAD_BALANCER_ID}")"
    mapfile -t lb_summary < <(printf '%s' "${lb_response}" | parse_lb_summary)
    lb_status="${lb_summary[3]}"
    current_lb_instances=("${lb_summary[@]:4}")

    echo "  lb-status=${lb_status:-<unknown>} attached-instances=${#current_lb_instances[@]}"

    if lb_has_instance "${lb_response}" "${TARGET_INSTANCE_ID}"; then
      echo
      echo "Instance ${TARGET_INSTANCE_ID} is now attached to load balancer ${lb_id}."
      echo "Final load balancer state:"
      print_lb_state "${lb_response}"
      echo
      echo "Note:"
      echo "  This confirms the LB configuration now includes the instance."
      echo "  Backend health and real traffic readiness still depend on health checks, firewall rules, and ingress availability."
      return
    fi

    sleep "${WAIT_INTERVAL_SECONDS}"
  done

  echo "Timed out waiting for load balancer ${TARGET_LOAD_BALANCER_ID} to include instance ${TARGET_INSTANCE_ID}." >&2
  exit 1
}

main "$@"
