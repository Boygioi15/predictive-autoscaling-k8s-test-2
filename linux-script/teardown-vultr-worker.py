#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Mapping, Sequence


TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off"}


class WorkerTeardownError(RuntimeError):
    """Raised when worker teardown cannot complete."""


@dataclass
class Config:
    target_node_name: str
    target_load_balancer_id: str
    vultr_api_key: str
    vultr_api_base: str
    wait_timeout_seconds: int
    wait_interval_seconds: int
    kubectl_drain_timeout: str
    kubectl_grace_period: str
    debug_instance_lookup: bool
    vultr_label_prefix: str
    vultr_hostname_prefix: str


@dataclass
class InstanceMatch:
    instance_id: str
    label: str
    hostname: str
    public_ip: str


def usage() -> str:
    return """Usage:
  VULTR_API_KEY=... \\
  VULTR_LOAD_BALANCER_ID=<lb-id> \\
  ./linux-script/teardown-vultr-worker.py <k8s-node-name>

Example:
  VULTR_API_KEY=... \\
  VULTR_LOAD_BALANCER_ID=abcd1234 \\
  ./linux-script/teardown-vultr-worker.py worker-5
"""


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print(usage(), file=sys.stderr, end="")
        return 1

    try:
        require_command("kubectl")
        config = load_config(args[0])

        print(f"Resolving Vultr instance for node name {config.target_node_name}...")
        instance_match = wait_for_instance_resolution_by_node_name(config)

        print("Resolved Vultr instance:")
        print(f"  instance-id: {instance_match.instance_id}")
        print(f"  label: {instance_match.label or '<none>'}")
        print(f"  hostname: {instance_match.hostname or '<none>'}")
        print(f"  public-ip: {instance_match.public_ip or '<none>'}")

        print()
        print("Step 1/3: detach node from Kubernetes")
        detach_node_from_cluster(config.target_node_name, config)

        print()
        print("Step 2/3: detach VM from load balancer")
        detach_vm_from_lb(config, instance_match.instance_id)

        print()
        print("Step 3/3: destroy Vultr VM")
        destroy_instance(config, instance_match.instance_id)

        print()
        print("Teardown completed:")
        print(f"  node-name: {config.target_node_name}")
        print(f"  load-balancer-id: {config.target_load_balancer_id}")
        print(f"  public-ip: {instance_match.public_ip}")
        print(f"  instance-id: {instance_match.instance_id}")
        return 0
    except WorkerTeardownError as error:
        print(str(error), file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as error:
        print(f"Command failed with exit code {error.returncode}: {format_command(error.cmd)}", file=sys.stderr)
        return error.returncode or 1
    except FileNotFoundError as error:
        print(f"No such file or command: {error.filename}", file=sys.stderr)
        return 1


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise WorkerTeardownError(f"Missing required environment variable: {name}")
    return value


def get_bool_env(name: str, default: str) -> bool:
    value = os.environ.get(name, default).strip().lower()
    if value in TRUE_VALUES:
        return True
    if value in FALSE_VALUES:
        return False
    raise WorkerTeardownError(f"Environment variable {name} must be one of: true, false, 1, 0, yes, no, on, off")


def get_int_env(name: str, default: str) -> int:
    value = os.environ.get(name, default).strip()
    try:
        return int(value)
    except ValueError as error:
        raise WorkerTeardownError(f"Environment variable {name} must be an integer. Got: {value}") from error


def load_config(target_node_name: str) -> Config:
    return Config(
        target_node_name=target_node_name,
        target_load_balancer_id=require_env("VULTR_LOAD_BALANCER_ID"),
        vultr_api_key=require_env("VULTR_API_KEY"),
        vultr_api_base=os.environ.get("VULTR_API_BASE", "https://api.vultr.com/v2"),
        wait_timeout_seconds=get_int_env("WAIT_TIMEOUT_SECONDS", "300"),
        wait_interval_seconds=get_int_env("WAIT_INTERVAL_SECONDS", "5"),
        kubectl_drain_timeout=os.environ.get("KUBECTL_DRAIN_TIMEOUT", "5m"),
        kubectl_grace_period=os.environ.get("KUBECTL_GRACE_PERIOD", "30"),
        debug_instance_lookup=get_bool_env("DEBUG_VULTR_INSTANCE_LOOKUP", "false"),
        vultr_label_prefix=os.environ.get("VULTR_LABEL_PREFIX", ""),
        vultr_hostname_prefix=os.environ.get("VULTR_HOSTNAME_PREFIX", ""),
    )


def require_command(name: str) -> None:
    if not shutil_which(name):
        raise WorkerTeardownError(f"Missing required command: {name}")


def shutil_which(name: str) -> bool:
    from shutil import which

    return which(name) is not None


def normalize_args(args: Sequence[object]) -> list[str]:
    return [str(arg) for arg in args]


def format_command(args: Sequence[object]) -> str:
    return " ".join(normalize_args(args))


def merge_env(extra_env: Mapping[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    if extra_env:
        env.update({key: str(value) for key, value in extra_env.items()})
    return env


def run_command(
    args: Sequence[object],
    *,
    check: bool = True,
    env: Mapping[str, str] | None = None,
    stdout=None,
    stderr=None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        normalize_args(args),
        check=check,
        env=merge_env(env),
        text=True,
        stdout=stdout,
        stderr=stderr,
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
        raise WorkerTeardownError(
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
        raise WorkerTeardownError(f"Vultr API request failed: {error.reason}") from error


def debug_log_response(config: Config, label: str, response: dict[str, object] | None) -> None:
    if not config.debug_instance_lookup:
        return
    print(f"DEBUG {label} response begin", file=sys.stderr)
    print(json.dumps(response, indent=2), file=sys.stderr)
    print(f"DEBUG {label} response end", file=sys.stderr)


def debug_log_instance_match(config: Config, instance_match: InstanceMatch) -> None:
    if not config.debug_instance_lookup:
        return
    print("DEBUG parsed instance_match count=4", file=sys.stderr)
    print(f"DEBUG instance_match[0]={instance_match.instance_id}", file=sys.stderr)
    print(f"DEBUG instance_match[1]={instance_match.label}", file=sys.stderr)
    print(f"DEBUG instance_match[2]={instance_match.hostname}", file=sys.stderr)
    print(f"DEBUG instance_match[3]={instance_match.public_ip}", file=sys.stderr)


def parse_instance_by_node_name(config: Config, data: dict[str, object] | list[object] | None) -> InstanceMatch:
    if not data:
        raise WorkerTeardownError(f"No Vultr instance found for node name: {config.target_node_name}")

    if isinstance(data, dict) and isinstance(data.get("instances"), list):
        instances = data.get("instances", [])
    elif isinstance(data, dict):
        instances = [data]
    elif isinstance(data, list):
        instances = data
    else:
        raise WorkerTeardownError(f"Unsupported Vultr instance response shape: {type(data).__name__}")

    expected_labels = {config.target_node_name}
    expected_hostnames = {config.target_node_name}
    if config.vultr_label_prefix:
        expected_labels.add(f"{config.vultr_label_prefix}{config.target_node_name}")
    if config.vultr_hostname_prefix:
        expected_hostnames.add(f"{config.vultr_hostname_prefix}{config.target_node_name}")

    candidates: list[dict[str, object]] = []
    for instance in instances:
        if not isinstance(instance, dict):
            continue
        label = str(instance.get("label", ""))
        hostname = str(instance.get("hostname", ""))
        if label in expected_labels or hostname in expected_hostnames:
            candidates.append(instance)

    if not candidates:
        raise WorkerTeardownError(f"No Vultr instance found for node name: {config.target_node_name}")

    if len(candidates) > 1:
        lines = [f"Multiple Vultr instances matched node name: {config.target_node_name}"]
        for instance in candidates:
            lines.append(
                "  id={id} label={label} hostname={hostname} public_ip={public_ip}".format(
                    id=instance.get("id", ""),
                    label=instance.get("label", ""),
                    hostname=instance.get("hostname", ""),
                    public_ip=instance.get("main_ip", ""),
                )
            )
        raise WorkerTeardownError("\n".join(lines))

    instance = candidates[0]
    return InstanceMatch(
        instance_id=str(instance.get("id", "")),
        label=str(instance.get("label", "")),
        hostname=str(instance.get("hostname", "")),
        public_ip=str(instance.get("main_ip", "")),
    )


def wait_for_instance_resolution_by_node_name(config: Config) -> InstanceMatch:
    deadline = time.monotonic() + config.wait_timeout_seconds
    attempt = 1
    last_response: dict[str, object] | None = None

    while time.monotonic() < deadline:
        last_response = api_call(config, "GET", "/instances?per_page=500")
        debug_log_response(config, "GET /instances?per_page=500", last_response)
        try:
            instance_match = parse_instance_by_node_name(config, last_response)
            debug_log_instance_match(config, instance_match)
            if instance_match.instance_id and instance_match.public_ip is not None:
                return instance_match
        except WorkerTeardownError:
            pass

        print(
            f"  Instance for node name {config.target_node_name} is not visible yet (attempt {attempt}), "
            f"retrying in {config.wait_interval_seconds}s..."
        )
        attempt += 1
        time.sleep(config.wait_interval_seconds)

    print(
        f"Timed out waiting for Vultr instance for node name {config.target_node_name} to appear in the instance list.",
        file=sys.stderr,
    )
    last_response = api_call(config, "GET", "/instances?per_page=500")
    debug_log_response(config, "GET /instances?per_page=500", last_response)
    instance_match = parse_instance_by_node_name(config, last_response)
    debug_log_instance_match(config, instance_match)
    if not instance_match.instance_id:
        raise WorkerTeardownError(f"Failed to resolve a complete Vultr instance record for node name {config.target_node_name}.")
    return instance_match


def instance_exists_in_list(data: dict[str, object] | None, target_instance_id: str) -> bool:
    if not data:
        return False
    instances = data.get("instances", [])
    if not isinstance(instances, list):
        return False
    return any(isinstance(instance, dict) and str(instance.get("id", "")) == target_instance_id for instance in instances)


def lb_has_instance(data: dict[str, object] | None, target_instance_id: str) -> bool:
    if not data:
        return False
    lb = data.get("load_balancer", {})
    if not isinstance(lb, dict):
        return False
    instances = lb.get("instances", [])
    if not isinstance(instances, list):
        return False
    return target_instance_id in [str(instance_id) for instance_id in instances]


def parse_lb_summary(data: dict[str, object] | None) -> tuple[str, str, str, str, list[str]]:
    if not data:
        return "", "", "", "", []
    lb = data.get("load_balancer", {})
    if not isinstance(lb, dict):
        return "", "", "", "", []
    instances = [str(instance_id) for instance_id in lb.get("instances", []) if instance_id]
    return (
        str(lb.get("id", "")),
        str(lb.get("label", "")),
        str(lb.get("region", "")),
        str(lb.get("status", "")),
        instances,
    )


def build_detach_payload(data: dict[str, object] | None, target_instance_id: str) -> dict[str, object]:
    if not data:
        return {"instances": []}
    lb = data.get("load_balancer", {})
    if not isinstance(lb, dict):
        return {"instances": []}
    remaining_instances = [
        str(instance_id)
        for instance_id in lb.get("instances", [])
        if instance_id and str(instance_id) != target_instance_id
    ]
    return {"instances": remaining_instances}


def node_exists(node_name: str) -> bool:
    result = run_command(
        ["kubectl", "get", "node", node_name],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def detach_node_from_cluster(node_name: str, config: Config) -> None:
    if not node_exists(node_name):
        print(f"Kubernetes node {node_name} is already absent, skipping cluster detach.")
        return

    print(f"Cordoning node {node_name}...")
    run_command(
        ["kubectl", "cordon", node_name],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    print(f"Draining node {node_name}...")
    run_command(
        [
            "kubectl",
            "drain",
            node_name,
            "--ignore-daemonsets",
            "--delete-emptydir-data",
            "--force",
            f"--timeout={config.kubectl_drain_timeout}",
            f"--grace-period={config.kubectl_grace_period}",
        ]
    )

    print(f"Deleting node {node_name} from the cluster...")
    run_command(["kubectl", "delete", "node", node_name])


def detach_vm_from_lb(config: Config, target_instance_id: str) -> None:
    print(f"Fetching current load balancer state for {config.target_load_balancer_id}...")
    lb_response = api_call(config, "GET", f"/load-balancers/{config.target_load_balancer_id}")

    if not lb_has_instance(lb_response, target_instance_id):
        print(f"Instance {target_instance_id} is already absent from load balancer {config.target_load_balancer_id}.")
        return

    patch_payload = build_detach_payload(lb_response, target_instance_id)

    print(f"Detaching instance {target_instance_id} from load balancer {config.target_load_balancer_id}...")
    api_call(config, "PATCH", f"/load-balancers/{config.target_load_balancer_id}", patch_payload)

    deadline = time.monotonic() + config.wait_timeout_seconds
    while time.monotonic() < deadline:
        lb_response = api_call(config, "GET", f"/load-balancers/{config.target_load_balancer_id}")
        _, _, _, lb_status, _ = parse_lb_summary(lb_response)

        if not lb_has_instance(lb_response, target_instance_id):
            print(f"Instance {target_instance_id} is no longer attached to load balancer {config.target_load_balancer_id}.")
            return

        print(f"  lb-status={lb_status or '<unknown>'} target-instance-still-attached=true")
        time.sleep(config.wait_interval_seconds)

    raise WorkerTeardownError(
        f"Timed out waiting for load balancer {config.target_load_balancer_id} to detach instance {target_instance_id}."
    )


def destroy_instance(config: Config, target_instance_id: str) -> None:
    print(f"Destroying Vultr instance {target_instance_id}...")
    api_call(config, "DELETE", f"/instances/{target_instance_id}")

    deadline = time.monotonic() + config.wait_timeout_seconds
    while time.monotonic() < deadline:
        instances_response = api_call(config, "GET", "/instances?per_page=500")
        if not instance_exists_in_list(instances_response, target_instance_id):
            print(f"Instance {target_instance_id} is gone from the Vultr instance list.")
            return

        print("  target-instance-still-present=true")
        time.sleep(config.wait_interval_seconds)

    raise WorkerTeardownError(
        f"Timed out waiting for instance {target_instance_id} to disappear from the Vultr instance list."
    )


if __name__ == "__main__":
    sys.exit(main())
