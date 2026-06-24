#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import random
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Mapping, Sequence


class WorkerE2EError(RuntimeError):
    """Raised when the worker create flow cannot complete."""


def usage() -> str:
    return """Usage:
  VULTR_API_KEY=... \\
  VULTR_REGION=sgp \\
  VULTR_PLAN=vc2-2c-4gb \\
  VULTR_OS_ID=2284 \\
  VULTR_LOAD_BALANCER_ID=<lb-id> \\
  VULTR_FIREWALL_GROUP_ID=<firewall-id> \\
  VULTR_VPC_ID=<vpc-id> \\
  VULTR_SSH_KEY_IDS=<ssh-key-id>[,<ssh-key-id>...] \\
  VULTR_ROOT_PUBLIC_KEY_FILE=~/.ssh/id_ed25519.pub \\
  K3S_URL=https://10.40.96.3:6443 \\
  K3S_TOKEN=... \\
  ./linux-script/create-worker-e2e.py [node-name]

Example:
  VULTR_API_KEY=... \\
  VULTR_REGION=sgp \\
  VULTR_PLAN=vc2-2c-4gb \\
  VULTR_OS_ID=2284 \\
  VULTR_LOAD_BALANCER_ID=lb-1234 \\
  VULTR_FIREWALL_GROUP_ID=abcd1234 \\
  VULTR_VPC_ID=dcba4321 \\
  VULTR_SSH_KEY_IDS=key-1 \\
  VULTR_ROOT_PUBLIC_KEY_FILE=~/.ssh/id_ed25519.pub \\
  K3S_URL=https://10.40.96.3:6443 \\
  K3S_TOKEN=K10...::server:... \\
  ./linux-script/create-worker-e2e.py worker-5
"""


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) > 1:
        print(usage(), file=sys.stderr, end="")
        return 1

    try:
        require_command("kubectl")
        require_env("K3S_URL")
        require_env("K3S_TOKEN")
        require_env("VULTR_API_KEY")
        require_env("VULTR_REGION")
        require_env("VULTR_PLAN")
        require_env("VULTR_OS_ID")
        load_balancer_id = require_env("VULTR_LOAD_BALANCER_ID")

        node_name = args[0] if len(args) == 1 else generate_node_name()
        flannel_iface = os.environ.get("FLANNEL_IFACE_DEFAULT", "enp8s0")
        bootstrap_ssh_user = os.environ.get("VULTR_BOOTSTRAP_SSH_USER", "root")
        bootstrap_ssh_host_mode = os.environ.get("BOOTSTRAP_SSH_HOST_MODE", "private")

        script_dir = Path(__file__).resolve().parent
        create_vultr_worker_script = script_dir / "create-vultr-worker.py"
        add_worker_script = script_dir / "add-k3s-worker-over-ssh.sh"
        attach_lb_script = script_dir / "attach-vm-to-lb.py"

        with tempfile.NamedTemporaryFile(mode="w+", encoding="utf-8", delete=True) as temp_file:
            result_path = Path(temp_file.name)

            print(f"Step 1/4: create worker VM {node_name}...")
            create_worker_env = os.environ.copy()
            create_worker_env["CREATE_RESULT_FILE"] = str(result_path)
            run_command([sys.executable, str(create_vultr_worker_script), node_name], env=create_worker_env)

            result = read_create_result(result_path)
            public_ip = str(result.get("public_ip", ""))
            private_ip = str(result.get("private_ip", ""))
            if not public_ip or not private_ip:
                raise WorkerE2EError("Create result file did not include both public and private IPs.")

            if bootstrap_ssh_host_mode == "public":
                ssh_target_host = public_ip
            elif bootstrap_ssh_host_mode == "private":
                ssh_target_host = private_ip
            else:
                raise WorkerE2EError(
                    f"BOOTSTRAP_SSH_HOST_MODE must be either public or private. Got: {bootstrap_ssh_host_mode}"
                )

            remove_stale_known_host(private_ip)
            remove_stale_known_host(f"{bootstrap_ssh_user}@{ssh_target_host}")
            wait_for_ssh_ready(f"{bootstrap_ssh_user}@{ssh_target_host}")

            print()
            print(f"Step 2/4: join node {node_name} to the cluster...")
            run_command([str(add_worker_script), f"{bootstrap_ssh_user}@{ssh_target_host}", private_ip, flannel_iface, node_name])

            print()
            print("Step 3/4: wait for node readiness...")
            wait_for_node_ready(node_name)

            print()
            print("Step 4/4: attach VM to load balancer...")
            run_command([sys.executable, str(attach_lb_script), public_ip])

            summary = {
                "node_name": result.get("node_name"),
                "instance_id": result.get("instance_id"),
                "public_ip": public_ip,
                "private_ip": private_ip,
                "load_balancer_id": load_balancer_id,
            }
            print()
            print("Worker create flow completed:")
            print(json.dumps(summary, indent=2))

        return 0
    except WorkerE2EError as error:
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
        raise WorkerE2EError(f"Missing required environment variable: {name}")
    return value


def require_command(name: str) -> None:
    if shutil.which(name) is None:
        raise WorkerE2EError(f"Missing required command: {name}")


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


def generate_node_name() -> str:
    prefix = os.environ.get("WORKER_NODE_NAME_PREFIX", "k3s-worker")
    return f"{prefix}-{int(time.time())}-{random.randint(0, 9999):04d}"


def read_create_result(result_path: Path) -> dict[str, object]:
    return json.loads(result_path.read_text(encoding="utf-8"))


def wait_for_node_ready(node_name: str) -> None:
    timeout = os.environ.get("KUBECTL_NODE_READY_TIMEOUT", "300s")
    registration_timeout_seconds = int(os.environ.get("KUBECTL_NODE_REGISTRATION_TIMEOUT_SECONDS", "300"))
    poll_interval_seconds = int(os.environ.get("KUBECTL_NODE_POLL_INTERVAL_SECONDS", "5"))
    deadline = time.monotonic() + registration_timeout_seconds

    print(f"Waiting for node {node_name} to register with the cluster...")
    while time.monotonic() < deadline:
        result = run_command(
            ["kubectl", "get", "node", node_name],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if result.returncode == 0:
            break
        time.sleep(poll_interval_seconds)

    result = run_command(
        ["kubectl", "get", "node", node_name],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        raise WorkerE2EError(f"Timed out waiting for node {node_name} to appear in the cluster.")

    print(f"Waiting for node {node_name} to become Ready...")
    run_command(["kubectl", "wait", "--for=condition=Ready", f"node/{node_name}", f"--timeout={timeout}"])


def extract_ssh_host(ssh_target: str) -> str:
    return ssh_target.rsplit("@", 1)[-1]


def remove_stale_known_host(ssh_target: str) -> None:
    known_hosts_file = os.environ.get("SSH_KNOWN_HOSTS_FILE", str(Path.home() / ".ssh/known_hosts"))
    ssh_host = extract_ssh_host(ssh_target)

    Path(known_hosts_file).parent.mkdir(parents=True, exist_ok=True)
    Path(known_hosts_file).touch(exist_ok=True)

    print(f"Removing stale SSH host key for {ssh_host}...")
    run_command(["ssh-keygen", "-R", ssh_host, "-f", known_hosts_file], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    run_command(["ssh-keygen", "-R", f"[{ssh_host}]:22", "-f", known_hosts_file], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def default_wait_ssh_options(known_hosts_file: str, connect_timeout_seconds: int) -> list[str]:
    return [
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        f"UserKnownHostsFile={known_hosts_file}",
        "-o",
        f"ConnectTimeout={connect_timeout_seconds}",
    ]


def wait_for_ssh_ready(ssh_target: str) -> None:
    known_hosts_file = os.environ.get("SSH_KNOWN_HOSTS_FILE", str(Path.home() / ".ssh/known_hosts"))
    timeout_seconds = int(os.environ.get("SSH_READY_TIMEOUT_SECONDS", "300"))
    poll_interval_seconds = int(os.environ.get("SSH_READY_POLL_INTERVAL_SECONDS", "5"))
    connect_timeout_seconds = int(os.environ.get("SSH_READY_CONNECT_TIMEOUT_SECONDS", "5"))
    deadline = time.monotonic() + timeout_seconds
    ssh_opts_env = os.environ.get("SSH_OPTS", "").strip()
    ssh_opts = shlex.split(ssh_opts_env) if ssh_opts_env else default_wait_ssh_options(known_hosts_file, connect_timeout_seconds)

    print(f"Waiting for SSH on {ssh_target}...")
    attempt = 1
    while time.monotonic() < deadline:
        result = run_command(
            ["ssh", *ssh_opts, ssh_target, "true"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if result.returncode == 0:
            print(f"SSH is ready on {ssh_target}.")
            return

        print(f"  SSH not ready yet on {ssh_target} (attempt {attempt}), retrying in {poll_interval_seconds}s...")
        attempt += 1
        time.sleep(poll_interval_seconds)

    raise WorkerE2EError(f"Timed out waiting for SSH on {ssh_target} after {timeout_seconds}s.")


if __name__ == "__main__":
    sys.exit(main())
