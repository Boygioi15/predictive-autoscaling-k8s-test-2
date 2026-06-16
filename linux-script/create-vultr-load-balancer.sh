#!/usr/bin/env bash

set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  VULTR_API_KEY=... \
  VULTR_LB_REGION=sgp \
  [VULTR_LB_NODES=3] \
  [VULTR_LB_FORWARDING_RULES_JSON='[{"frontend_protocol":"http","frontend_port":80,"backend_protocol":"http","backend_port":80}]'] \
  [VULTR_LB_HEALTH_CHECK_JSON='{"protocol":"http","port":80,"path":"/healthz","check_interval":10,"response_timeout":5,"unhealthy_threshold":3,"healthy_threshold":3}'] \
  ./linux-script/create-vultr-load-balancer.sh <lb-label>

Example:
  VULTR_API_KEY=... \
  VULTR_LB_REGION=sgp \
  VULTR_LB_NODES=3 \
  ./linux-script/create-vultr-load-balancer.sh thesis-lb
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
  python3 - "$LB_LABEL" <<'PY'
import json
import os
import sys

label = sys.argv[1]

forwarding_rules = json.loads(os.environ.get(
    "VULTR_LB_FORWARDING_RULES_JSON",
    '[{"frontend_protocol":"http","frontend_port":80,"backend_protocol":"http","backend_port":80}]',
))

health_check = json.loads(os.environ.get(
    "VULTR_LB_HEALTH_CHECK_JSON",
    '{"protocol":"http","port":80,"path":"/healthz","check_interval":10,"response_timeout":5,"unhealthy_threshold":3,"healthy_threshold":3}',
))

payload = {
    "region": os.environ["VULTR_LB_REGION"],
    "label": label,
    "nodes": int(os.environ.get("VULTR_LB_NODES", "3")),
    "instances": [],
    "forwarding_rules": forwarding_rules,
    "health_check": health_check,
    "proxy_protocol": os.environ.get("VULTR_LB_PROXY_PROTOCOL", "false").lower() == "true",
    "balancing_algorithm": os.environ.get("VULTR_LB_BALANCING_ALGORITHM", "roundrobin").strip() or "roundrobin",
    "timeout": int(os.environ.get("VULTR_LB_TIMEOUT", "600")),
}

http_version = os.environ.get("VULTR_LB_HTTP_VERSION", "").strip()
if http_version:
    if http_version == "2":
        payload["http2"] = True
        payload["http3"] = False
    elif http_version == "3":
        payload["http2"] = True
        payload["http3"] = True
    else:
        raise SystemExit("VULTR_LB_HTTP_VERSION must be either 2 or 3.")

sticky_sessions_enabled = os.environ.get("VULTR_LB_STICKY_SESSIONS", "false").lower() == "true"
cookie_name = os.environ.get("VULTR_LB_COOKIE_NAME", "VLBSTICKY").strip()
if sticky_sessions_enabled:
    payload["sticky_session"] = {"cookie_name": cookie_name}

vpc_id = os.environ.get("VULTR_LB_VPC_ID", "").strip()
if vpc_id:
    payload["vpc"] = vpc_id

ssl_json = os.environ.get("VULTR_LB_SSL_JSON", "").strip()
if ssl_json:
    payload["ssl"] = json.loads(ssl_json)

auto_ssl_json = os.environ.get("VULTR_LB_AUTO_SSL_JSON", "").strip()
if auto_ssl_json:
    payload["auto_ssl"] = json.loads(auto_ssl_json)

auto_ssl_domain = os.environ.get("VULTR_LB_AUTO_SSL_DOMAIN", "").strip()
if auto_ssl_domain:
    domain = auto_ssl_domain
    if "://" in domain:
        raise SystemExit("VULTR_LB_AUTO_SSL_DOMAIN must not include http:// or https://.")
    domain = domain.strip(".")
    parts = domain.split(".")
    if len(parts) < 2:
        raise SystemExit("VULTR_LB_AUTO_SSL_DOMAIN must contain a valid domain like example.com.")
    payload["auto_ssl"] = {
        "domain_zone": ".".join(parts[-2:]),
        "domain_sub": ".".join(parts[:-2]),
    }

has_ssl = "ssl" in payload or "auto_ssl" in payload
ssl_redirect_requested = os.environ.get("VULTR_LB_SSL_REDIRECT", "false").lower() == "true"

uses_https_rule = any(
    str(rule.get("frontend_protocol", "")).lower() == "https"
    or str(rule.get("backend_protocol", "")).lower() == "https"
    for rule in forwarding_rules
)

if uses_https_rule and not has_ssl:
    raise SystemExit(
        "HTTPS forwarding rules require SSL material. "
        "Set VULTR_LB_SSL_JSON or VULTR_LB_AUTO_SSL_DOMAIN/AUTO_SSL_JSON."
    )

if ssl_redirect_requested and not has_ssl:
    raise SystemExit(
        "VULTR_LB_SSL_REDIRECT=true requires SSL material. "
        "Set VULTR_LB_SSL_JSON or VULTR_LB_AUTO_SSL_DOMAIN/AUTO_SSL_JSON."
    )

if ssl_redirect_requested:
    payload["ssl_redirect"] = True

print(json.dumps(payload))
PY
}

parse_create_response() {
  python3 -c '
import json
import sys

data = json.load(sys.stdin)
lb = data.get("load_balancer", data)
print(lb.get("id", ""))
' 
}

parse_lb_state() {
  python3 -c '
import json
import sys

data = json.load(sys.stdin)
lb = data.get("load_balancer", data)
ipv4 = lb.get("ipv4") or lb.get("ip") or lb.get("IPV4") or ""
ipv6 = lb.get("ipv6") or lb.get("IPV6") or ""
print(lb.get("status", ""))
print(ipv4)
print(ipv6)
print(lb.get("label", ""))
print(lb.get("region", ""))
print(lb.get("nodes", ""))
'
}

write_result_file() {
  local public_ip="$1"
  local status="$2"
  local result_file="${CREATE_RESULT_FILE:-}"

  if [[ -z "${result_file}" ]]; then
    return
  fi

  python3 - "$result_file" "$LB_LABEL" "$LB_ID" "$public_ip" "$status" <<'PY'
import json
import sys
from pathlib import Path

result_file, label, lb_id, public_ip, status = sys.argv[1:]

payload = {
    "label": label,
    "instance_id": lb_id,
    "public_ip": public_ip,
    "private_ip": "",
    "status": status,
}

path = Path(result_file)
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(payload), encoding="utf-8")
PY
}

main() {
  if [[ $# -ne 1 ]]; then
    usage
    exit 1
  fi

  require_command curl
  require_command python3
  require_env VULTR_API_KEY

  LB_LABEL="$1"
  VULTR_API_BASE="${VULTR_API_BASE:-https://api.vultr.com/v2}"
  VULTR_LB_REGION="${VULTR_LB_REGION:-${VULTR_REGION:-}}"
  WAIT_TIMEOUT_SECONDS="${WAIT_TIMEOUT_SECONDS:-900}"
  WAIT_INTERVAL_SECONDS="${WAIT_INTERVAL_SECONDS:-5}"

  require_env VULTR_LB_REGION

  local payload
  local create_response
  local deadline
  local state_response=""
  local status=""
  local public_ip=""
  local ipv6=""
  local label=""
  local region=""
  local nodes=""

  payload="$(build_payload)"

  echo "Creating Vultr load balancer ${LB_LABEL}..."
  create_response="$(api_call POST /load-balancers "${payload}")"
  LB_ID="$(printf '%s' "${create_response}" | parse_create_response)"

  if [[ -z "${LB_ID}" ]]; then
    echo "Load balancer create response did not include an id." >&2
    exit 1
  fi

  echo "Created load balancer ${LB_ID}, waiting for active state..."
  deadline=$((SECONDS + WAIT_TIMEOUT_SECONDS))

  while (( SECONDS < deadline )); do
    state_response="$(api_call GET "/load-balancers/${LB_ID}")"
    mapfile -t state < <(printf '%s' "${state_response}" | parse_lb_state)
    status="${state[0]}"
    public_ip="${state[1]}"
    ipv6="${state[2]}"
    label="${state[3]}"
    region="${state[4]}"
    nodes="${state[5]}"

    if [[ "${status}" == "active" && -n "${public_ip}" ]]; then
      write_result_file "${public_ip}" "${status}"
      echo
      echo "Load balancer is ready."
      echo "  label: ${label:-${LB_LABEL}}"
      echo "  id: ${LB_ID}"
      echo "  region: ${region:-${VULTR_LB_REGION}}"
      echo "  nodes: ${nodes:-<unknown>}"
      echo "  public-ip: ${public_ip}"
      echo "  ipv6: ${ipv6:-<none>}"
      return
    fi

    echo "  status=${status:-<pending>} public_ip=${public_ip:-<pending>}"
    sleep "${WAIT_INTERVAL_SECONDS}"
  done

  echo "Timed out waiting for load balancer ${LB_ID} to become active." >&2
  exit 1
}

main "$@"
