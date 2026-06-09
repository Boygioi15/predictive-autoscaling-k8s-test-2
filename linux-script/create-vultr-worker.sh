#!/usr/bin/env bash

set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  VULTR_API_KEY=... \
  VULTR_REGION=sgp \
  VULTR_PLAN=vc2-2c-4gb \
  VULTR_OS_ID=2284 \
  VULTR_FIREWALL_GROUP_ID=<firewall-id> \
  VULTR_VPC_ID=<vpc-id> \
  VULTR_SSH_KEY_IDS=<ssh-key-id>[,<ssh-key-id>...] \
  VULTR_ROOT_PUBLIC_KEY_FILE=~/.ssh/id_ed25519.pub \
  ./linux-script/create-vultr-worker.sh <node-name>

Example:
  VULTR_API_KEY=... \
  VULTR_REGION=sgp \
  VULTR_PLAN=vc2-2c-4gb \
  VULTR_OS_ID=2284 \
  VULTR_FIREWALL_GROUP_ID=abcd1234 \
  VULTR_VPC_ID=dcba4321 \
  VULTR_SSH_KEY_IDS=key-1 \
  VULTR_ROOT_PUBLIC_KEY_FILE=~/.ssh/id_ed25519.pub \
  K3S_URL=https://10.40.96.3:6443 \
  K3S_TOKEN=K10... \
  ./linux-script/create-vultr-worker.sh worker-5
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

build_payload() {
  python3 - "$NODE_NAME" <<'PY'
import base64
import json
import os
from pathlib import Path
import sys

node_name = sys.argv[1]

def csv(name):
    raw = os.environ.get(name, "").strip()
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]

def read_root_public_key():
    inline_key = os.environ.get("VULTR_ROOT_PUBLIC_KEY", "").strip()
    if inline_key:
        return inline_key

    key_file = os.environ.get("VULTR_ROOT_PUBLIC_KEY_FILE", "").strip()
    if not key_file:
        return ""

    expanded = Path(key_file).expanduser()
    if not expanded.is_file():
        raise SystemExit(f"Root public key file not found: {expanded}")

    return expanded.read_text(encoding="utf-8").strip()

def build_root_cloud_init(public_key: str):
    return "\n".join([
        "#cloud-config",
        "disable_root: false",
        "ssh_pwauth: false",
        "users:",
        "  - name: root",
        "    lock_passwd: true",
        "    ssh_authorized_keys:",
        f"      - {public_key}",
    ])

payload = {
    "region": os.environ["VULTR_REGION"],
    "plan": os.environ["VULTR_PLAN"],
    "os_id": int(os.environ["VULTR_OS_ID"]),
    "label": os.environ.get("VULTR_LABEL_PREFIX", "") + node_name,
    "hostname": os.environ.get("VULTR_HOSTNAME_PREFIX", "") + node_name,
    "activation_email": False,
}

firewall_group_id = os.environ.get("VULTR_FIREWALL_GROUP_ID", "").strip()
if firewall_group_id:
    payload["firewall_group_id"] = firewall_group_id

ssh_key_ids = csv("VULTR_SSH_KEY_IDS")
if ssh_key_ids:
    payload["ssh_key_ids"] = ssh_key_ids

tags = csv("VULTR_TAGS")
if tags:
    payload["tags"] = tags

user_data = os.environ.get("VULTR_USER_DATA", "")
root_public_key = read_root_public_key()
if not user_data and root_public_key:
    user_data = build_root_cloud_init(root_public_key)
if user_data:
    payload["user_data"] = base64.b64encode(user_data.encode("utf-8")).decode("ascii")

script_id = os.environ.get("VULTR_SCRIPT_ID", "").strip()
if script_id:
    payload["script_id"] = script_id

print(json.dumps(payload))
PY
}

parse_create_response() {
  python3 -c '
import json
import sys

raw = sys.stdin.read()
if not raw.strip():
    raise SystemExit("Vultr create response was empty.")

data = json.loads(raw)
instance = data["instance"]
print(instance["id"])
'
}

parse_instance_state() {
  python3 -c '
import json
import sys

raw = sys.stdin.read()
if not raw.strip():
    raise SystemExit("Vultr instance state response was empty.")

data = json.loads(raw)
instance = data["instance"]
print(instance.get("status", ""))
print(instance.get("server_status", ""))
print(instance.get("main_ip", ""))
print(instance.get("internal_ip", ""))
'
}

print_next_steps() {
  local public_ip="$1"
  local private_ip="$2"
  local server_status="$3"
  local bootstrap_ssh_user
  bootstrap_ssh_user="${VULTR_BOOTSTRAP_SSH_USER:-root}"

  echo
  echo "Instance is ready."
  echo "  node-name: ${NODE_NAME}"
  echo "  instance-id: ${INSTANCE_ID}"
  echo "  server-status: ${server_status}"
  echo "  public-ip: ${public_ip}"
  echo "  private-ip: ${private_ip}"

  echo
  echo "Next step:"
  if [[ -n "${K3S_URL:-}" && -n "${K3S_TOKEN:-}" ]]; then
    echo "  K3S_URL='${K3S_URL}' K3S_TOKEN='<redacted>' ./linux-script/add-k3s-worker-over-ssh.sh ${bootstrap_ssh_user}@${private_ip} ${private_ip} ${FLANNEL_IFACE_DEFAULT} ${NODE_NAME}"
  else
    echo "  K3S_URL=https://10.40.96.3:6443 K3S_TOKEN='<token>' ./linux-script/add-k3s-worker-over-ssh.sh ${bootstrap_ssh_user}@${private_ip} ${private_ip} ${FLANNEL_IFACE_DEFAULT} ${NODE_NAME}"
  fi

  write_result_file "${public_ip}" "${private_ip}" "${server_status}"
}

write_result_file() {
  local public_ip="$1"
  local private_ip="$2"
  local server_status="$3"
  local result_file="${CREATE_RESULT_FILE:-}"

  if [[ -z "${result_file}" ]]; then
    return
  fi

  python3 - "$result_file" "$NODE_NAME" "$INSTANCE_ID" "$public_ip" "$private_ip" "$server_status" <<'PY'
import json
import sys
from pathlib import Path

result_file, node_name, instance_id, public_ip, private_ip, server_status = sys.argv[1:]

payload = {
    "node_name": node_name,
    "instance_id": instance_id,
    "public_ip": public_ip,
    "private_ip": private_ip,
    "server_status": server_status,
}

path = Path(result_file)
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(payload), encoding="utf-8")
PY
}

attach_vpc_to_instance() {
  local instance_id="$1"
  local vpc_id="$2"
  local attach_payload

  attach_payload="$(python3 -c 'import json, sys; print(json.dumps({"vpc_id": sys.argv[1]}))' "${vpc_id}")"
  api_call POST "/instances/${instance_id}/vpcs/attach" "${attach_payload}" false >/dev/null
}

main() {
  if [[ $# -ne 1 ]]; then
    usage
    exit 1
  fi

  require_command curl
  require_command python3
  require_env VULTR_API_KEY
  require_env VULTR_REGION
  require_env VULTR_PLAN
  require_env VULTR_OS_ID

  NODE_NAME="$1"
  VULTR_API_BASE="${VULTR_API_BASE:-https://api.vultr.com/v2}"
  FLANNEL_IFACE_DEFAULT="${FLANNEL_IFACE_DEFAULT:-enp8s0}"
  WAIT_TIMEOUT_SECONDS="${WAIT_TIMEOUT_SECONDS:-900}"
  WAIT_INTERVAL_SECONDS="${WAIT_INTERVAL_SECONDS:-5}"
  DEBUG_VULTR_CREATE="${DEBUG_VULTR_CREATE:-false}"

  local payload
  payload="$(build_payload)"

  if [[ "${DEBUG_VULTR_CREATE}" == "true" ]]; then
    echo "Create payload:"
    echo "${payload}"
  fi

  local create_response

  echo "Creating Vultr instance for node ${NODE_NAME}..."
  create_response="$(api_call POST /instances "${payload}")"

  if [[ "${DEBUG_VULTR_CREATE}" == "true" ]]; then
    echo "Create response:"
    echo "${create_response}"
  fi

  INSTANCE_ID="$(printf '%s' "${create_response}" | parse_create_response)"
  echo "Created instance ${INSTANCE_ID}, waiting for ready state..."

  local deadline
  deadline=$((SECONDS + WAIT_TIMEOUT_SECONDS))

  local status=""
  local server_status=""
  local public_ip=""
  local private_ip=""
  local instance_state_response=""
  local vpc_attached="false"
  local require_private_ip="false"
  local instance_ready="false"
  if [[ -n "${VULTR_VPC_ID:-}" ]]; then
    require_private_ip="true"
  fi
  while (( SECONDS < deadline )); do
    instance_state_response="$(api_call GET "/instances/${INSTANCE_ID}")"
    mapfile -t state < <(printf '%s' "${instance_state_response}" | parse_instance_state)
    status="${state[0]}"
    server_status="${state[1]}"
    public_ip="${state[2]}"
    private_ip="${state[3]}"
    instance_ready="false"

    if [[ "${status}" == "active" && -n "${public_ip}" && "${vpc_attached}" == "false" && -n "${VULTR_VPC_ID:-}" ]]; then
      echo "Attaching VPC ${VULTR_VPC_ID} to instance ${INSTANCE_ID}..."
      attach_vpc_to_instance "${INSTANCE_ID}" "${VULTR_VPC_ID}"
      vpc_attached="true"
      sleep "${WAIT_INTERVAL_SECONDS}"
      continue
    fi

    if [[ "${status}" == "active" && "${server_status}" == "ok" && -n "${public_ip}" && ( "${require_private_ip}" == "false" || -n "${private_ip}" ) ]]; then
      instance_ready="true"
    fi

    if [[ "${instance_ready}" == "true" ]]; then
      print_next_steps "${public_ip}" "${private_ip}" "${server_status}"
      return
    fi

    echo "  status=${status} server_status=${server_status} public_ip=${public_ip:-<pending>} private_ip=${private_ip:-<pending>}"
    sleep "${WAIT_INTERVAL_SECONDS}"
  done

  echo "Timed out waiting for instance ${INSTANCE_ID} to become ready (status=active, server_status=ok)." >&2
  exit 1
}

main "$@"
