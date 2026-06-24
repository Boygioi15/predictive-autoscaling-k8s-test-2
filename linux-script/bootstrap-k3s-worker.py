#!/usr/bin/env python3

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off"}


class BootstrapError(RuntimeError):
    """Raised when worker bootstrap cannot continue."""


@dataclass
class Config:
    k3s_url: str
    k3s_token: str
    k3s_channel: str
    k3s_install_script_url: str
    allow_https: bool
    node_name: str
    node_ip: str
    flannel_iface: str


def main() -> int:
    try:
        require_root()
        config = load_config()

        if not config.node_ip and config.flannel_iface:
            config.node_ip = derive_node_ip_from_iface(config.flannel_iface)

        if not config.flannel_iface and config.node_ip:
            config.flannel_iface = derive_iface_from_node_ip(config.node_ip)

        if not config.node_ip:
            raise BootstrapError("Unable to determine NODE_IP. Set NODE_IP explicitly or provide FLANNEL_IFACE.")

        if not config.flannel_iface:
            raise BootstrapError("Unable to determine FLANNEL_IFACE. Set FLANNEL_IFACE explicitly.")

        configure_ufw(config)
        write_k3s_config(config)
        install_k3s_agent(config)
        run_command(["systemctl", "enable", "--now", "k3s-agent"])
        run_command(["systemctl", "restart", "k3s-agent"])
        print_summary(config)
        return 0
    except BootstrapError as error:
        print(str(error), file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as error:
        print(f"Command failed with exit code {error.returncode}: {format_command(error.cmd)}", file=sys.stderr)
        return error.returncode or 1
    except FileNotFoundError as error:
        print(f"No such file or command: {error.filename}", file=sys.stderr)
        return 1


def require_root() -> None:
    if os.geteuid() != 0:
        raise BootstrapError("This script must run as root.")


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise BootstrapError(f"Missing required environment variable: {name}")
    return value


def get_bool_env(name: str, default: str) -> bool:
    raw_value = os.environ.get(name, default).strip().lower()
    if raw_value in TRUE_VALUES:
        return True
    if raw_value in FALSE_VALUES:
        return False
    raise BootstrapError(f"Environment variable {name} must be one of: true, false, 1, 0, yes, no, on, off")


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
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        normalize_args(args),
        check=check,
        env=merge_env(env),
        text=True,
        capture_output=capture_output,
    )


def pipe_command_output(
    producer_args: Sequence[object],
    consumer_args: Sequence[object],
    *,
    consumer_env: Mapping[str, str] | None = None,
) -> None:
    producer = subprocess.Popen(normalize_args(producer_args), stdout=subprocess.PIPE)
    if producer.stdout is None:
        raise BootstrapError(f"Unable to read stdout from: {format_command(producer_args)}")

    try:
        consumer = subprocess.run(
            normalize_args(consumer_args),
            stdin=producer.stdout,
            env=merge_env(consumer_env),
            check=False,
        )
    finally:
        producer.stdout.close()

    producer_returncode = producer.wait()
    if consumer.returncode != 0:
        raise subprocess.CalledProcessError(consumer.returncode, normalize_args(consumer_args))
    if producer_returncode != 0:
        raise subprocess.CalledProcessError(producer_returncode, normalize_args(producer_args))


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def load_config() -> Config:
    return Config(
        k3s_url=require_env("K3S_URL"),
        k3s_token=require_env("K3S_TOKEN"),
        k3s_channel=os.environ.get("K3S_CHANNEL", "stable"),
        k3s_install_script_url=os.environ.get("K3S_INSTALL_SCRIPT_URL", "https://get.k3s.io"),
        allow_https=get_bool_env("ALLOW_HTTPS", "false"),
        node_name=os.environ.get("NODE_NAME", socket.gethostname().split(".", 1)[0]),
        node_ip=os.environ.get("NODE_IP", ""),
        flannel_iface=os.environ.get("FLANNEL_IFACE", ""),
    )


def derive_node_ip_from_iface(iface: str) -> str:
    result = run_command(["ip", "-4", "-o", "addr", "show", "dev", iface], capture_output=True)
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 4:
            return parts[3].split("/", 1)[0]
    return ""


def derive_iface_from_node_ip(node_ip: str) -> str:
    result = run_command(["ip", "-4", "-o", "addr", "show"], capture_output=True)
    prefix = f"{node_ip}/"
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[3].startswith(prefix):
            return parts[1]
    return ""


def write_k3s_config(config: Config) -> None:
    k3s_dir = Path("/etc/rancher/k3s")
    k3s_dir.mkdir(parents=True, exist_ok=True)

    lines = [
        f"node-ip: {config.node_ip}",
        f"node-name: {config.node_name}",
    ]

    if config.flannel_iface:
        lines.append(f"flannel-iface: {config.flannel_iface}")

    (k3s_dir / "config.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def configure_ufw(config: Config) -> None:
    if not command_exists("ufw"):
        print("ufw not installed, skipping firewall rules.")
        return

    for rule in (
        "22/tcp",
        "80/tcp",
        "8472/udp",
        "9100/udp",
        "9100/tcp",
        "10250/tcp",
    ):
        run_command(["ufw", "allow", rule])

    if config.allow_https:
        run_command(["ufw", "allow", "443/tcp"])


def install_k3s_agent(config: Config) -> None:
    pipe_command_output(
        ["curl", "-sfL", config.k3s_install_script_url],
        ["sh", "-"],
        consumer_env={
            "INSTALL_K3S_CHANNEL": config.k3s_channel,
            "K3S_URL": config.k3s_url,
            "K3S_TOKEN": config.k3s_token,
            "INSTALL_K3S_EXEC": "agent",
        },
    )


def print_summary(config: Config) -> None:
    print("k3s worker bootstrap completed.")
    print(f"  node-name: {config.node_name}")
    print(f"  node-ip: {config.node_ip}")
    if config.flannel_iface:
        print(f"  flannel-iface: {config.flannel_iface}")
    else:
        print("  flannel-iface: <not set>")


if __name__ == "__main__":
    sys.exit(main())
