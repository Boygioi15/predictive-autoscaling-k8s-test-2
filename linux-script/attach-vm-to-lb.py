#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


class AttachVMError(RuntimeError):
    """Raised when the VM cannot be attached to the load balancer."""


@dataclass
class Config:
    target_load_balancer_id: str
    target_public_ip: str
    vultr_api_key: str
    vultr_api_base: str
    wait_timeout_seconds: int
    wait_interval_seconds: int


@dataclass
class InstanceSummary:
    instance_id: str
    label: str
    region: str
    status: str
    server_status: str
    public_ip: str


@dataclass
class LoadBalancerSummary:
    lb_id: str
    label: str
    region: str
    status: str
    ip: str
    instances: list[str]


def usage() -> str:
    return """Usage:
  VULTR_API_KEY=... \\
  VULTR_LOAD_BALANCER_ID=<lb-id> \\
  ./linux-script/attach-vm-to-lb.py <vm-public-ip>

Example:
  VULTR_API_KEY=... \\
  VULTR_LOAD_BALANCER_ID=abcd1234 \\
  ./linux-script/attach-vm-to-lb.py 149.28.132.166
"""


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print(usage(), file=sys.stderr, end="")
        return 1

    try:
        config = load_config(args[0])

        print(f"Resolving Vultr instance for public IP {config.target_public_ip}...")
        instance_summary = wait_for_instance_resolution(config)

        print("Resolved instance:")
        print(f"  instance-id: {instance_summary.instance_id}")
        print(f"  label: {instance_summary.label or '<none>'}")
        print(f"  region: {instance_summary.region or '<unknown>'}")
        print(f"  status: {instance_summary.status or '<unknown>'}")
        print(f"  server-status: {instance_summary.server_status or '<unknown>'}")

        print()
        print("Fetching current load balancer state...")
        lb_response = api_call(config, "GET", f"/load-balancers/{config.target_load_balancer_id}")
        lb_summary = parse_lb_summary(lb_response)

        print("Current load balancer:")
        print(f"  lb-id: {lb_summary.lb_id}")
        print(f"  label: {lb_summary.label or '<none>'}")
        print(f"  region: {lb_summary.region or '<unknown>'}")
        print(f"  status: {lb_summary.status or '<unknown>'}")
        print(f"  attached-instances: {len(lb_summary.instances)}")

        if instance_summary.region != lb_summary.region:
            raise AttachVMError(
                f"Instance region ({instance_summary.region}) does not match load balancer region ({lb_summary.region})."
            )

        if lb_has_instance(lb_summary, instance_summary.instance_id):
            print()
            print(f"Instance {instance_summary.instance_id} is already attached to load balancer {lb_summary.lb_id}.")
            print("Current load balancer state:")
            print_lb_state(lb_summary)
            return 0

        patch_payload = build_patch_payload(lb_summary, instance_summary.instance_id)

        print()
        print(f"Updating load balancer {lb_summary.lb_id} with merged backend list...")
        api_call(config, "PATCH", f"/load-balancers/{config.target_load_balancer_id}", patch_payload)

        deadline = time.monotonic() + config.wait_timeout_seconds
        while time.monotonic() < deadline:
            lb_response = api_call(config, "GET", f"/load-balancers/{config.target_load_balancer_id}")
            lb_summary = parse_lb_summary(lb_response)

            print(f"  lb-status={lb_summary.status or '<unknown>'} attached-instances={len(lb_summary.instances)}")

            if lb_has_instance(lb_summary, instance_summary.instance_id):
                print()
                print(f"Instance {instance_summary.instance_id} is now attached to load balancer {lb_summary.lb_id}.")
                print("Final load balancer state:")
                print_lb_state(lb_summary)
                print()
                print("Note:")
                print("  This confirms the LB configuration now includes the instance.")
                print(
                    "  Backend health and real traffic readiness still depend on health checks, firewall rules, "
                    "and ingress availability."
                )
                return 0

            time.sleep(config.wait_interval_seconds)

        raise AttachVMError(
            f"Timed out waiting for load balancer {config.target_load_balancer_id} "
            f"to include instance {instance_summary.instance_id}."
        )
    except AttachVMError as error:
        print(str(error), file=sys.stderr)
        return 1


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise AttachVMError(f"Missing required environment variable: {name}")
    return value


def get_int_env(name: str, default: str) -> int:
    value = os.environ.get(name, default).strip()
    try:
        return int(value)
    except ValueError as error:
        raise AttachVMError(f"Environment variable {name} must be an integer. Got: {value}") from error


def load_config(target_public_ip: str) -> Config:
    return Config(
        target_load_balancer_id=require_env("VULTR_LOAD_BALANCER_ID"),
        target_public_ip=target_public_ip,
        vultr_api_key=require_env("VULTR_API_KEY"),
        vultr_api_base=os.environ.get("VULTR_API_BASE", "https://api.vultr.com/v2"),
        wait_timeout_seconds=get_int_env("WAIT_TIMEOUT_SECONDS", "300"),
        wait_interval_seconds=get_int_env("WAIT_INTERVAL_SECONDS", "5"),
    )


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
        raise AttachVMError(
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
        raise AttachVMError(f"Vultr API request failed: {error.reason}") from error


def parse_instance_id_by_public_ip(data: dict[str, object] | None, target_public_ip: str) -> str:
    if not data:
        raise AttachVMError(f"No Vultr instance found with public IP: {target_public_ip}")

    instances = data.get("instances", [])
    if not isinstance(instances, list):
        raise AttachVMError("Unsupported Vultr instance response shape.")

    for instance in instances:
        if isinstance(instance, dict) and str(instance.get("main_ip", "")) == target_public_ip:
            return str(instance.get("id", ""))

    raise AttachVMError(f"No Vultr instance found with public IP: {target_public_ip}")


def parse_instance_summary(data: dict[str, object] | None, target_instance_id: str) -> InstanceSummary:
    if not data:
        raise AttachVMError(f"No Vultr instance found with id: {target_instance_id}")

    instances = data.get("instances", [])
    if not isinstance(instances, list):
        raise AttachVMError("Unsupported Vultr instance response shape.")

    for instance in instances:
        if isinstance(instance, dict) and str(instance.get("id", "")) == target_instance_id:
            return InstanceSummary(
                instance_id=target_instance_id,
                label=str(instance.get("label", "")),
                region=str(instance.get("region", "")),
                status=str(instance.get("status", "")),
                server_status=str(instance.get("server_status", "")),
                public_ip=str(instance.get("main_ip", "")),
            )

    raise AttachVMError(f"No Vultr instance found with id: {target_instance_id}")


def parse_lb_summary(data: dict[str, object] | None) -> LoadBalancerSummary:
    if not data:
        raise AttachVMError("Vultr load balancer response was empty.")

    lb = data.get("load_balancer", {})
    if not isinstance(lb, dict):
        raise AttachVMError("Unsupported Vultr load balancer response shape.")

    return LoadBalancerSummary(
        lb_id=str(lb.get("id", "")),
        label=str(lb.get("label", "")),
        region=str(lb.get("region", "")),
        status=str(lb.get("status", "")),
        ip=str(lb.get("ip", "")),
        instances=[str(instance_id) for instance_id in lb.get("instances", []) if instance_id],
    )


def build_patch_payload(lb_summary: LoadBalancerSummary, target_instance_id: str) -> dict[str, object]:
    merged_instances: list[str] = []
    seen: set[str] = set()

    for instance_id in [*lb_summary.instances, target_instance_id]:
        if not instance_id or instance_id in seen:
            continue
        merged_instances.append(instance_id)
        seen.add(instance_id)

    return {"instances": merged_instances}


def lb_has_instance(lb_summary: LoadBalancerSummary, target_instance_id: str) -> bool:
    return target_instance_id in lb_summary.instances


def print_lb_state(lb_summary: LoadBalancerSummary) -> None:
    summary = {
        "id": lb_summary.lb_id,
        "label": lb_summary.label,
        "region": lb_summary.region,
        "status": lb_summary.status,
        "ip": lb_summary.ip,
        "instances": lb_summary.instances,
        "instance_count": len(lb_summary.instances),
    }
    print(json.dumps(summary, indent=2))


def wait_for_instance_resolution(config: Config) -> InstanceSummary:
    deadline = time.monotonic() + config.wait_timeout_seconds
    attempt = 1
    last_response: dict[str, object] | None = None

    while time.monotonic() < deadline:
        last_response = api_call(config, "GET", "/instances?per_page=500")
        try:
            target_instance_id = parse_instance_id_by_public_ip(last_response, config.target_public_ip)
            return parse_instance_summary(last_response, target_instance_id)
        except AttachVMError:
            pass

        print(
            f"  Instance for public IP {config.target_public_ip} is not visible yet "
            f"(attempt {attempt}), retrying in {config.wait_interval_seconds}s..."
        )
        attempt += 1
        time.sleep(config.wait_interval_seconds)

    print(
        f"Timed out waiting for Vultr instance with public IP {config.target_public_ip} to appear in the instance list.",
        file=sys.stderr,
    )
    last_response = api_call(config, "GET", "/instances?per_page=500")
    target_instance_id = parse_instance_id_by_public_ip(last_response, config.target_public_ip)
    return parse_instance_summary(last_response, target_instance_id)


if __name__ == "__main__":
    sys.exit(main())
