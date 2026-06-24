#!/usr/bin/env python3

from __future__ import annotations

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path


TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off"}


class WorkerCreateError(RuntimeError):
    """Raised when a worker VM cannot be created."""


@dataclass
class Config:
    node_name: str
    vultr_api_key: str
    vultr_region: str
    vultr_plan: str
    vultr_os_id: int
    vultr_api_base: str
    flannel_iface_default: str
    wait_timeout_seconds: int
    wait_interval_seconds: int
    debug_vultr_create: bool


def usage() -> str:
    return """Usage:
  VULTR_API_KEY=... \\
  VULTR_REGION=sgp \\
  VULTR_PLAN=vc2-2c-4gb \\
  VULTR_OS_ID=2284 \\
  VULTR_FIREWALL_GROUP_ID=<firewall-id> \\
  VULTR_VPC_ID=<vpc-id> \\
  VULTR_SSH_KEY_IDS=<ssh-key-id>[,<ssh-key-id>...] \\
  VULTR_ROOT_PUBLIC_KEY_FILE=~/.ssh/id_ed25519.pub \\
  ./linux-script/create-vultr-worker.py <node-name>

Example:
  VULTR_API_KEY=... \\
  VULTR_REGION=sgp \\
  VULTR_PLAN=vc2-2c-4gb \\
  VULTR_OS_ID=2284 \\
  VULTR_FIREWALL_GROUP_ID=abcd1234 \\
  VULTR_VPC_ID=dcba4321 \\
  VULTR_SSH_KEY_IDS=key-1 \\
  VULTR_ROOT_PUBLIC_KEY_FILE=~/.ssh/id_ed25519.pub \\
  K3S_URL=https://10.40.96.3:6443 \\
  K3S_TOKEN=K10... \\
  ./linux-script/create-vultr-worker.py worker-5
"""


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print(usage(), file=sys.stderr, end="")
        return 1

    try:
        config = load_config(args[0])
        payload = build_payload(config)

        if config.debug_vultr_create:
            print("Create payload:")
            print(json.dumps(payload))

        print(f"Creating Vultr instance for node {config.node_name}...")
        create_response = api_call(config, "POST", "/instances", payload)

        if config.debug_vultr_create:
            print("Create response:")
            print(json.dumps(create_response))

        instance_id = parse_create_response(create_response)
        print(f"Created instance {instance_id}, waiting for ready state...")

        public_ip, private_ip, server_status = wait_for_instance_ready(config, instance_id)
        print_next_steps(config, instance_id, public_ip, private_ip, server_status)
        write_result_file(config, instance_id, public_ip, private_ip, server_status)
        return 0
    except WorkerCreateError as error:
        print(str(error), file=sys.stderr)
        return 1


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise WorkerCreateError(f"Missing required environment variable: {name}")
    return value


def get_bool_env(name: str, default: str) -> bool:
    value = os.environ.get(name, default).strip().lower()
    if value in TRUE_VALUES:
        return True
    if value in FALSE_VALUES:
        return False
    raise WorkerCreateError(f"Environment variable {name} must be one of: true, false, 1, 0, yes, no, on, off")


def get_int_env(name: str, default: str) -> int:
    value = os.environ.get(name, default).strip()
    try:
        return int(value)
    except ValueError as error:
        raise WorkerCreateError(f"Environment variable {name} must be an integer. Got: {value}") from error


def csv_env(name: str) -> list[str]:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def load_config(node_name: str) -> Config:
    try:
        vultr_os_id = int(require_env("VULTR_OS_ID"))
    except ValueError as error:
        raise WorkerCreateError(f"Environment variable VULTR_OS_ID must be an integer. Got: {os.environ.get('VULTR_OS_ID')}") from error

    return Config(
        node_name=node_name,
        vultr_api_key=require_env("VULTR_API_KEY"),
        vultr_region=require_env("VULTR_REGION"),
        vultr_plan=require_env("VULTR_PLAN"),
        vultr_os_id=vultr_os_id,
        vultr_api_base=os.environ.get("VULTR_API_BASE", "https://api.vultr.com/v2"),
        flannel_iface_default=os.environ.get("FLANNEL_IFACE_DEFAULT", "enp8s0"),
        wait_timeout_seconds=get_int_env("WAIT_TIMEOUT_SECONDS", "900"),
        wait_interval_seconds=get_int_env("WAIT_INTERVAL_SECONDS", "5"),
        debug_vultr_create=get_bool_env("DEBUG_VULTR_CREATE", "false"),
    )


def read_root_public_key() -> str:
    inline_key = os.environ.get("VULTR_ROOT_PUBLIC_KEY", "").strip()
    if inline_key:
        return inline_key

    key_file = os.environ.get("VULTR_ROOT_PUBLIC_KEY_FILE", "").strip()
    if not key_file:
        return ""

    expanded = Path(key_file).expanduser()
    if not expanded.is_file():
        raise WorkerCreateError(f"Root public key file not found: {expanded}")
    return expanded.read_text(encoding="utf-8").strip()


def build_root_cloud_init(public_key: str) -> str:
    return "\n".join(
        [
            "#cloud-config",
            "disable_root: false",
            "ssh_pwauth: false",
            "users:",
            "  - name: root",
            "    lock_passwd: true",
            "    ssh_authorized_keys:",
            f"      - {public_key}",
        ]
    )


def build_payload(config: Config) -> dict[str, object]:
    payload: dict[str, object] = {
        "region": config.vultr_region,
        "plan": config.vultr_plan,
        "os_id": config.vultr_os_id,
        "label": os.environ.get("VULTR_LABEL_PREFIX", "") + config.node_name,
        "hostname": os.environ.get("VULTR_HOSTNAME_PREFIX", "") + config.node_name,
        "activation_email": False,
    }

    firewall_group_id = os.environ.get("VULTR_FIREWALL_GROUP_ID", "").strip()
    if firewall_group_id:
        payload["firewall_group_id"] = firewall_group_id

    ssh_key_ids = csv_env("VULTR_SSH_KEY_IDS")
    if ssh_key_ids:
        payload["ssh_key_ids"] = ssh_key_ids

    tags = csv_env("VULTR_TAGS")
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

    return payload


def api_call(config: Config, method: str, path: str, body: dict[str, object] | None = None) -> dict[str, object] | None:
    url = f"{config.vultr_api_base}{path}"
    headers = {
        "Authorization": f"Bearer {config.vultr_api_key}",
    }
    data = None

    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")

    request = urllib.request.Request(url, method=method, headers=headers, data=data)
    try:
        with urllib.request.urlopen(request) as response:
            raw_body = response.read().decode("utf-8")
            if not raw_body.strip():
                return None
            return json.loads(raw_body)
    except urllib.error.HTTPError as error:
        response_body = error.read().decode("utf-8", errors="replace")
        response_lines = [f"    {line}" for line in response_body.splitlines()]
        if not response_lines:
            response_lines = ["    <empty>"]
        raise WorkerCreateError(
            "\n".join(
                [
                    "Vultr API request failed.",
                    f"  method: {method}",
                    f"  path: {path}",
                    f"  http_status: {error.code}",
                    "  response_body:",
                    *response_lines,
                ]
            )
        ) from error
    except urllib.error.URLError as error:
        raise WorkerCreateError(f"Vultr API request failed: {error.reason}") from error


def parse_create_response(data: dict[str, object] | None) -> str:
    if not data:
        raise WorkerCreateError("Vultr create response was empty.")

    instance = data.get("instance")
    if not isinstance(instance, dict):
        raise WorkerCreateError("Vultr create response did not include an instance object.")

    instance_id = str(instance.get("id", "")).strip()
    if not instance_id:
        raise WorkerCreateError("Vultr create response did not include an instance id.")
    return instance_id


def parse_instance_state(data: dict[str, object] | None) -> tuple[str, str, str, str]:
    if not data:
        raise WorkerCreateError("Vultr instance state response was empty.")

    instance = data.get("instance")
    if not isinstance(instance, dict):
        raise WorkerCreateError("Vultr instance state response did not include an instance object.")

    return (
        str(instance.get("status", "")),
        str(instance.get("server_status", "")),
        str(instance.get("main_ip", "")),
        str(instance.get("internal_ip", "")),
    )


def attach_vpc_to_instance(config: Config, instance_id: str, vpc_id: str) -> None:
    api_call(config, "POST", f"/instances/{instance_id}/vpcs/attach", {"vpc_id": vpc_id})


def wait_for_instance_ready(config: Config, instance_id: str) -> tuple[str, str, str]:
    deadline = time.monotonic() + config.wait_timeout_seconds
    vpc_id = os.environ.get("VULTR_VPC_ID", "").strip()
    vpc_attached = False
    require_private_ip = bool(vpc_id)

    while time.monotonic() < deadline:
        state = api_call(config, "GET", f"/instances/{instance_id}")
        status, server_status, public_ip, private_ip = parse_instance_state(state)

        if status == "active" and public_ip and not vpc_attached and vpc_id:
            print(f"Attaching VPC {vpc_id} to instance {instance_id}...")
            attach_vpc_to_instance(config, instance_id, vpc_id)
            vpc_attached = True
            time.sleep(config.wait_interval_seconds)
            continue

        instance_ready = (
            status == "active"
            and server_status == "ok"
            and bool(public_ip)
            and (not require_private_ip or bool(private_ip))
        )
        if instance_ready:
            return public_ip, private_ip, server_status

        pending_public_ip = public_ip or "<pending>"
        pending_private_ip = private_ip or "<pending>"
        print(f"  status={status} server_status={server_status} public_ip={pending_public_ip} private_ip={pending_private_ip}")
        time.sleep(config.wait_interval_seconds)

    raise WorkerCreateError(
        f"Timed out waiting for instance {instance_id} to become ready (status=active, server_status=ok)."
    )


def print_next_steps(config: Config, instance_id: str, public_ip: str, private_ip: str, server_status: str) -> None:
    bootstrap_ssh_user = os.environ.get("VULTR_BOOTSTRAP_SSH_USER", "root")

    print()
    print("Instance is ready.")
    print(f"  node-name: {config.node_name}")
    print(f"  instance-id: {instance_id}")
    print(f"  server-status: {server_status}")
    print(f"  public-ip: {public_ip}")
    print(f"  private-ip: {private_ip}")
    print()
    print("Next step:")

    if os.environ.get("K3S_URL") and os.environ.get("K3S_TOKEN"):
        print(
            "  "
            f"K3S_URL='{os.environ['K3S_URL']}' "
            "K3S_TOKEN='<redacted>' "
            f"./linux-script/add-k3s-worker-over-ssh.sh {bootstrap_ssh_user}@{private_ip} {private_ip} "
            f"{config.flannel_iface_default} {config.node_name}"
        )
    else:
        print(
            "  "
            "K3S_URL=https://10.40.96.3:6443 "
            "K3S_TOKEN='<token>' "
            f"./linux-script/add-k3s-worker-over-ssh.sh {bootstrap_ssh_user}@{private_ip} {private_ip} "
            f"{config.flannel_iface_default} {config.node_name}"
        )


def write_result_file(config: Config, instance_id: str, public_ip: str, private_ip: str, server_status: str) -> None:
    result_file = os.environ.get("CREATE_RESULT_FILE", "").strip()
    if not result_file:
        return

    payload = {
        "node_name": config.node_name,
        "instance_id": instance_id,
        "public_ip": public_ip,
        "private_ip": private_ip,
        "server_status": server_status,
    }

    path = Path(result_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
