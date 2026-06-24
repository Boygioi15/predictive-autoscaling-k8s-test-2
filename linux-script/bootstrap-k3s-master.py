#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Mapping, Sequence


TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off"}


class BootstrapError(RuntimeError):
    """Raised when the bootstrap flow cannot proceed."""


@dataclass
class Config:
    project_dir: Path
    log_dir: Path
    master_node_name: str
    master_public_ip: str
    k3s_channel: str
    k3s_install_script_url: str
    custom_scaler_image: str
    install_monitoring: bool
    install_ingress: bool
    deploy_custom_scaler: bool
    apply_custom_scaler_sample: bool
    worker_bootstrap_ssh_host_mode: str
    vultr_bootstrap_ssh_user: str
    worker_k3s_url: str
    node_ip: str
    advertise_address: str
    flannel_iface: str


def main() -> int:
    try:
        require_root()
        config = load_config()
        install_base_packages()
        ensure_log_dir(config)

        if not config.node_ip and config.flannel_iface:
            config.node_ip = derive_node_ip_from_iface(config.flannel_iface)
            config.advertise_address = config.node_ip

        if not config.flannel_iface and config.node_ip:
            config.flannel_iface = derive_iface_from_node_ip(config.node_ip)

        if not config.node_ip:
            raise BootstrapError("Unable to determine the master node IP.")

        if not config.flannel_iface:
            raise BootstrapError("Unable to determine FLANNEL_IFACE. Set FLANNEL_IFACE_DEFAULT explicitly.")

        configure_ufw()
        write_k3s_config(config)
        install_k3s_server(config)
        wait_for_k3s_ready(config)
        prepare_kubeconfig()
        install_helm()
        label_and_taint_master(config)
        patch_local_path_provisioner_for_infra_taint()

        if config.install_monitoring:
            install_monitoring_stack(config)

        if config.install_ingress:
            install_ingress_stack(config)

        if config.deploy_custom_scaler:
            apply_custom_scaler_bundle(config)
            write_vm_job_secret_files()
            apply_vm_job_config(config)
            apply_vm_job_secret()
            wait_for_custom_scaler_ready()

            if config.apply_custom_scaler_sample:
                apply_custom_scaler_sample(config)

        write_access_files(config)
        print_summary(config)
        return 0
    except BootstrapError as error:
        print(str(error), file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as error:
        command = format_command(error.cmd)
        print(f"Command failed with exit code {error.returncode}: {command}", file=sys.stderr)
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


def trim_trailing_slash(value: str) -> str:
    trimmed = value.rstrip("/")
    return trimmed or value


def load_config() -> Config:
    project_dir = Path(trim_trailing_slash(require_env("PROJECT_DIR")))
    master_node_name = require_env("MASTER_NODE_NAME")
    master_public_ip = os.environ.get("MASTER_PUBLIC_IP", "")
    master_private_ip = os.environ.get("MASTER_PRIVATE_IP", "")

    node_ip = master_private_ip or master_public_ip
    advertise_address = master_private_ip or master_public_ip
    flannel_iface = os.environ.get("FLANNEL_IFACE_DEFAULT", "")

    config = Config(
        project_dir=project_dir,
        log_dir=Path(os.environ.get("BOOTSTRAP_LOG_DIR", str(project_dir / "work-log"))),
        master_node_name=master_node_name,
        master_public_ip=master_public_ip,
        k3s_channel=os.environ.get("K3S_CHANNEL", "stable"),
        k3s_install_script_url=os.environ.get("K3S_INSTALL_SCRIPT_URL", "https://get.k3s.io"),
        custom_scaler_image=os.environ.get("CUSTOM_SCALER_IMAGE", "docker.io/boygioi/custom-scaler:latest"),
        install_monitoring=get_bool_env("INSTALL_MONITORING", "true"),
        install_ingress=get_bool_env("INSTALL_INGRESS", "false"),
        deploy_custom_scaler=get_bool_env("DEPLOY_CUSTOM_SCALER", "true"),
        apply_custom_scaler_sample=get_bool_env("APPLY_CUSTOM_SCALER_SAMPLE", "true"),
        worker_bootstrap_ssh_host_mode=os.environ.get("WORKER_BOOTSTRAP_SSH_HOST_MODE", "private"),
        vultr_bootstrap_ssh_user=os.environ.get("VULTR_BOOTSTRAP_SSH_USER", "root"),
        worker_k3s_url=os.environ.get("WORKER_K3S_URL", ""),
        node_ip=node_ip,
        advertise_address=advertise_address,
        flannel_iface=flannel_iface,
    )

    if config.deploy_custom_scaler:
        for name in (
            "WORKER_VULTR_REGION",
            "WORKER_VULTR_PLAN",
            "WORKER_VULTR_OS_ID",
            "VULTR_LOAD_BALANCER_ID",
            "VULTR_API_KEY",
            "VM_JOB_PRIVATE_KEY_PATH",
            "VM_JOB_PUBLIC_KEY_PATH",
        ):
            require_env(name)

    return config


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
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    input_text: str | None = None,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        normalize_args(args),
        check=check,
        cwd=str(cwd) if cwd else None,
        env=merge_env(env),
        input=input_text,
        text=True,
        capture_output=capture_output,
    )


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


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


def install_base_packages() -> None:
    env = {"DEBIAN_FRONTEND": "noninteractive"}
    run_command(["apt-get", "update"], env=env)
    run_command(
        [
            "apt-get",
            "install",
            "-y",
            "ca-certificates",
            "curl",
            "make",
            "python3",
            "python3-pip",
            "rsync",
        ],
        env=env,
    )


def configure_ufw() -> None:
    if not command_exists("ufw"):
        print("ufw not installed, skipping firewall rules.")
        return

    for rule in (
        "6443/tcp",
        "8472/udp",
        "10250/tcp",
        "9100/tcp",
    ):
        run_command(["ufw", "allow", rule])


def write_k3s_config(config: Config) -> None:
    k3s_dir = Path("/etc/rancher/k3s")
    k3s_dir.mkdir(parents=True, exist_ok=True)

    lines = [
        f"node-name: {config.master_node_name}",
        f"node-ip: {config.node_ip}",
        f"advertise-address: {config.advertise_address}",
        'write-kubeconfig-mode: "0644"',
        "disable:",
        "  - traefik",
    ]

    if config.flannel_iface:
        lines.append(f"flannel-iface: {config.flannel_iface}")

    lines.extend(
        [
            "tls-san:",
            f"  - {config.node_ip}",
        ]
    )

    if config.master_public_ip:
        lines.append(f"  - {config.master_public_ip}")

    (k3s_dir / "config.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")


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


def install_k3s_server(config: Config) -> None:
    pipe_command_output(
        ["curl", "-sfL", config.k3s_install_script_url],
        ["sh", "-"],
        consumer_env={
            "INSTALL_K3S_CHANNEL": config.k3s_channel,
            "INSTALL_K3S_EXEC": "server",
        },
    )


def install_helm() -> None:
    if command_exists("helm"):
        return  

    pipe_command_output(
        ["curl", "-fsSL", "https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3"],
        ["bash"],
    )


def wait_for_k3s_ready(config: Config) -> None:
    os.environ["KUBECONFIG"] = "/etc/rancher/k3s/k3s.yaml"

    run_command(["systemctl", "enable", "--now", "k3s"])
    run_command(["systemctl", "restart", "k3s"])

    print("Waiting for the master node to register...")
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        result = subprocess.run(
            ["kubectl", "get", "node", config.master_node_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode == 0:
            run_command(["kubectl", "wait", "--for=condition=Ready", f"node/{config.master_node_name}", "--timeout=300s"])
            return
        time.sleep(5)

    raise BootstrapError(f"Timed out waiting for node {config.master_node_name} to become Ready.")


def prepare_kubeconfig() -> None:
    kube_dir = Path("/root/.kube")
    kube_dir.mkdir(parents=True, exist_ok=True)
    target = kube_dir / "config"
    shutil.copyfile("/etc/rancher/k3s/k3s.yaml", target)
    os.chmod(target, 0o600)


def ensure_log_dir(config: Config) -> None:
    config.log_dir.mkdir(parents=True, exist_ok=True)
    os.environ["BOOTSTRAP_LOG_DIR"] = str(config.log_dir)


def run_logged_step(log_dir: Path, step_name: str, args: Sequence[object], *, cwd: Path | None = None) -> None:
    log_file = log_dir / f"{step_name}.log"
    print(f"Logging {step_name} to {log_file}")

    with log_file.open("w", encoding="utf-8") as handle:
        process = subprocess.Popen(
            normalize_args(args),
            cwd=str(cwd) if cwd else None,
            env=merge_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        if process.stdout is None:
            raise BootstrapError(f"Unable to capture output for step: {step_name}")

        try:
            for line in process.stdout:
                sys.stdout.write(line)
                handle.write(line)
            returncode = process.wait()
        finally:
            process.stdout.close()

    if returncode != 0:
        raise BootstrapError(f"Step {step_name} failed. See {log_file}")


def capture_output(args: Sequence[object], *, cwd: Path | None = None) -> str:
    try:
        result = run_command(args, check=False, capture_output=True, cwd=cwd)
    except FileNotFoundError as error:
        return f"No such file or command: {error.filename}\n"
    return f"{result.stdout}{result.stderr}"


def list_resources(args: Sequence[object]) -> list[str]:
    try:
        result = run_command(args, check=False, capture_output=True)
    except FileNotFoundError:
        return []
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def write_section(handle, title: str, content: str) -> None:
    handle.write(f"=== {title} ===\n")
    handle.write(content)
    if content and not content.endswith("\n"):
        handle.write("\n")
    handle.write("\n")


def collect_monitoring_debug_info(config: Config) -> None:
    diagnostics_file = config.log_dir / "monitoring-install-diagnostics.log"

    job_names = list_resources(["kubectl", "get", "jobs", "-n", "monitoring", "-o", "name"])
    pod_names = list_resources(["kubectl", "get", "pods", "-n", "monitoring", "-o", "name"])

    with diagnostics_file.open("w", encoding="utf-8") as handle:
        write_section(handle, "Timestamp", datetime.now().astimezone().isoformat(timespec="seconds"))
        write_section(handle, "Helm List", capture_output(["helm", "list", "-n", "monitoring"]))
        write_section(
            handle,
            "Helm Status",
            capture_output(["helm", "status", "monitoring-stack", "-n", "monitoring", "--show-resources"]),
        )
        write_section(handle, "Helm History", capture_output(["helm", "history", "monitoring-stack", "-n", "monitoring"]))
        write_section(handle, "Monitoring Pods", capture_output(["kubectl", "get", "pods", "-n", "monitoring", "-o", "wide"]))
        write_section(handle, "Monitoring Jobs", capture_output(["kubectl", "get", "jobs", "-n", "monitoring", "-o", "wide"]))
        write_section(
            handle,
            "Monitoring Events",
            capture_output(["kubectl", "get", "events", "-n", "monitoring", "--sort-by=.lastTimestamp"]),
        )
        write_section(handle, "Monitoring All Resources", capture_output(["kubectl", "get", "all", "-n", "monitoring"]))
        write_section(handle, "Monitoring PVCs", capture_output(["kubectl", "get", "pvc", "-n", "monitoring"]))
        write_section(handle, "PersistentVolumes", capture_output(["kubectl", "get", "pv"]))
        write_section(handle, "StorageClasses", capture_output(["kubectl", "get", "storageclass"]))
        write_section(
            handle,
            "Local Path Provisioner Pods",
            capture_output(["kubectl", "get", "pods", "-n", "kube-system", "-l", "app=local-path-provisioner", "-o", "wide"]),
        )
        write_section(
            handle,
            "Local Path ConfigMap",
            capture_output(["kubectl", "get", "configmap", "local-path-config", "-n", "kube-system", "-o", "yaml"]),
        )

        handle.write("=== Monitoring Job Describe ===\n")
        for job in job_names:
            handle.write(f"--- {job} ---\n")
            handle.write(capture_output(["kubectl", "describe", "-n", "monitoring", job]))
            handle.write("\n")
        handle.write("\n")

        handle.write("=== Monitoring Pod Describe ===\n")
        for pod in pod_names:
            handle.write(f"--- {pod} ---\n")
            handle.write(capture_output(["kubectl", "describe", "-n", "monitoring", pod]))
            handle.write("\n")
        handle.write("\n")

        handle.write("=== Monitoring Pod Logs ===\n")
        for pod in pod_names:
            handle.write(f"--- {pod} ---\n")
            handle.write(
                capture_output(["kubectl", "logs", "-n", "monitoring", pod, "--all-containers=true", "--tail=200"])
            )
            handle.write("\n")

    print(f"Wrote monitoring diagnostics to {diagnostics_file}", file=sys.stderr)


def patch_local_path_provisioner_for_infra_taint() -> None:
    print("Patching local-path provisioner for role=infra:NoSchedule...")

    run_command(
        [
            "kubectl",
            "-n",
            "kube-system",
            "patch",
            "deployment",
            "local-path-provisioner",
            "--type",
            "merge",
            "-p",
            (
                "spec:\n"
                "  template:\n"
                "    spec:\n"
                "      tolerations:\n"
                "        - key: role\n"
                "          operator: Equal\n"
                "          value: infra\n"
                "          effect: NoSchedule\n"
            ),
        ]
    )

    config_json = run_command(
        ["kubectl", "-n", "kube-system", "get", "configmap", "local-path-config", "-o", "json"],
        capture_output=True,
    ).stdout
    config = json.loads(config_json)
    helper = config.get("data", {}).get("helperPod.yaml", "")

    infra_toleration = (
        "          tolerations:\n"
        "            - key: role\n"
        "              operator: Equal\n"
        "              value: infra\n"
        "              effect: NoSchedule\n"
    )
    infra_snippet = (
        "\n"
        "            - key: role\n"
        "              operator: Equal\n"
        "              value: infra\n"
        "              effect: NoSchedule"
    )

    if "key: role" not in helper:
        marker = "          tolerations:"
        if marker in helper:
            helper = helper.replace(marker, marker + infra_snippet, 1)
        elif "        spec:\n" in helper:
            helper = helper.replace("        spec:\n", f"        spec:\n{infra_toleration}", 1)

    config.setdefault("data", {})["helperPod.yaml"] = helper

    run_command(["kubectl", "apply", "-f", "-"], input_text=json.dumps(config))
    run_command(["kubectl", "rollout", "restart", "deployment/local-path-provisioner", "-n", "kube-system"])
    run_command(["kubectl", "rollout", "status", "deployment/local-path-provisioner", "-n", "kube-system", "--timeout=300s"])


def label_and_taint_master(config: Config) -> None:
    run_command(["kubectl", "label", "node", config.master_node_name, "role=infra", "--overwrite"])
    run_command(["kubectl", "taint", "node", config.master_node_name, "role=infra:NoSchedule", "--overwrite"])


def install_monitoring_stack(config: Config) -> None:
    try:
        run_logged_step(config.log_dir, "monitoring-install", ["make", "install-helm-monitor"], cwd=config.project_dir)
    except BootstrapError:
        collect_monitoring_debug_info(config)
        raise

    run_logged_step(config.log_dir, "monitoring-service-monitor", ["make", "deploy-monitor"], cwd=config.project_dir)


def install_ingress_stack(config: Config) -> None:
    run_command(["make", "install-helm-ingress"], cwd=config.project_dir)


def split_yaml_documents(text: str) -> list[str]:
    return [document.strip() for document in re.split(r"(?m)^---\s*$", text) if document.strip()]


def extract_kind_and_name(document: str) -> tuple[str | None, str | None]:
    kind_match = re.search(r"(?m)^kind:\s*(.+?)\s*$", document)
    name_match = re.search(r"(?m)^  name:\s*(.+?)\s*$", document)
    kind = kind_match.group(1).strip() if kind_match else None
    name = name_match.group(1).strip() if name_match else None
    return kind, name


def filter_custom_scaler_bundle(config: Config) -> str:
    manifest = run_command(
        ["kubectl", "kustomize", str(config.project_dir / "custom-scaler/config/default")],
        capture_output=True,
    ).stdout

    filtered_documents: list[str] = []
    skip_names = {"custom-scaler-vm-job-config", "custom-scaler-vm-job-secret"}

    for document in split_yaml_documents(manifest):
        kind, name = extract_kind_and_name(document)
        if kind in {"ConfigMap", "Secret"} and name in skip_names:
            continue
        filtered_documents.append(document)

    if not filtered_documents:
        return ""

    return "\n---\n".join(filtered_documents) + "\n"


def apply_custom_scaler_bundle(config: Config) -> None:
    bundle = filter_custom_scaler_bundle(config)
    if not bundle:
        raise BootstrapError("Custom scaler bundle is empty after filtering.")

    run_command(["kubectl", "apply", "-f", "-"], input_text=bundle)
    run_command(
        [
            "kubectl",
            "-n",
            "custom-scaler-system",
            "set",
            "image",
            "deployment/custom-scaler-controller-manager",
            f"manager={config.custom_scaler_image}",
        ]
    )


def write_vm_job_secret_files() -> None:
    private_key_path = Path(require_env("VM_JOB_PRIVATE_KEY_PATH"))
    public_key_path = Path(require_env("VM_JOB_PUBLIC_KEY_PATH"))

    if not private_key_path.is_file():
        raise BootstrapError(f"VM job private key file not found: {private_key_path}")
    if not public_key_path.is_file():
        raise BootstrapError(f"VM job public key file not found: {public_key_path}")

    ssh_dir = Path("/root/.ssh")
    ssh_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(ssh_dir, 0o700)

    private_target = ssh_dir / "vm-job_ed25519"
    public_target = ssh_dir / "vm-job_ed25519.pub"
    shutil.copyfile(private_key_path, private_target)
    shutil.copyfile(public_key_path, public_target)
    os.chmod(private_target, 0o600)
    os.chmod(public_target, 0o644)


def create_and_apply_manifest(create_args: Sequence[object]) -> None:
    manifest = run_command(create_args, capture_output=True).stdout
    run_command(["kubectl", "apply", "-f", "-"], input_text=manifest)


def apply_vm_job_config(config: Config) -> None:
    worker_k3s_url = config.worker_k3s_url or f"https://{config.advertise_address}:6443"
    create_and_apply_manifest(
        [
            "kubectl",
            "-n",
            "custom-scaler-system",
            "create",
            "configmap",
            "custom-scaler-vm-job-config",
            "--from-literal=VULTR_REGION=" + os.environ.get("WORKER_VULTR_REGION", ""),
            "--from-literal=VULTR_PLAN=" + os.environ.get("WORKER_VULTR_PLAN", ""),
            "--from-literal=VULTR_OS_ID=" + os.environ.get("WORKER_VULTR_OS_ID", ""),
            "--from-literal=VULTR_FIREWALL_GROUP_ID=" + os.environ.get("WORKER_VULTR_FIREWALL_GROUP_ID", ""),
            "--from-literal=VULTR_VPC_ID=" + os.environ.get("WORKER_VULTR_VPC_ID", ""),
            "--from-literal=VULTR_SSH_KEY_IDS=" + os.environ.get("WORKER_VULTR_SSH_KEY_IDS", ""),
            "--from-literal=VULTR_LOAD_BALANCER_ID=" + require_env("VULTR_LOAD_BALANCER_ID"),
            "--from-literal=VULTR_BOOTSTRAP_SSH_USER=" + config.vultr_bootstrap_ssh_user,
            "--from-literal=K3S_URL=" + worker_k3s_url,
            "--from-literal=FLANNEL_IFACE_DEFAULT=" + config.flannel_iface,
            "--from-literal=BOOTSTRAP_SSH_HOST_MODE=" + config.worker_bootstrap_ssh_host_mode,
            "--from-literal=VULTR_ROOT_PUBLIC_KEY_FILE=/var/run/vm-job-secret/id_ed25519.pub",
            "--from-literal=SSH_OPTS=-i /var/run/vm-job-secret/id_ed25519 -o StrictHostKeyChecking=accept-new",
            "--dry-run=client",
            "-o",
            "yaml",
        ]
    )


def apply_vm_job_secret() -> None:
    k3s_token = Path("/var/lib/rancher/k3s/server/node-token").read_text(encoding="utf-8").strip()
    create_and_apply_manifest(
        [
            "kubectl",
            "-n",
            "custom-scaler-system",
            "create",
            "secret",
            "generic",
            "custom-scaler-vm-job-secret",
            "--from-literal=VULTR_API_KEY=" + require_env("VULTR_API_KEY"),
            "--from-literal=K3S_TOKEN=" + k3s_token,
            "--from-file=id_ed25519=/root/.ssh/vm-job_ed25519",
            "--from-file=id_ed25519.pub=/root/.ssh/vm-job_ed25519.pub",
            "--dry-run=client",
            "-o",
            "yaml",
        ]
    )


def wait_for_custom_scaler_ready() -> None:
    run_command(["kubectl", "wait", "--for=condition=Established", "crd/customscalers.autoscaling.my.domain", "--timeout=300s"])
    run_command(
        [
            "kubectl",
            "rollout",
            "status",
            "deployment/custom-scaler-controller-manager",
            "-n",
            "custom-scaler-system",
            "--timeout=300s",
        ]
    )


def apply_custom_scaler_sample(config: Config) -> None:
    run_command(["kubectl", "apply", "-f", str(config.project_dir / "custom-scaler/config/samples/autoscaling_v1_customscaler.yaml")])


def write_access_files(config: Config) -> None:
    shares_dir = config.project_dir / "shares"
    shares_dir.mkdir(parents=True, exist_ok=True)

    k3s_token = Path("/var/lib/rancher/k3s/server/node-token").read_text(encoding="utf-8").strip()
    worker_env_path = shares_dir / "k3s-worker.env"
    private_kubeconfig_path = shares_dir / "kubeconfig-private.yaml"
    public_kubeconfig_path = shares_dir / "kubeconfig-public.yaml"

    worker_env_path.write_text(
        f"K3S_URL=https://{config.advertise_address}:6443\nK3S_TOKEN={k3s_token}\n",
        encoding="utf-8",
    )

    kubeconfig = Path("/etc/rancher/k3s/k3s.yaml").read_text(encoding="utf-8")
    private_kubeconfig_path.write_text(
        kubeconfig.replace("https://127.0.0.1:6443", f"https://{config.advertise_address}:6443"),
        encoding="utf-8",
    )

    if config.master_public_ip:
        public_kubeconfig_path.write_text(
            kubeconfig.replace("https://127.0.0.1:6443", f"https://{config.master_public_ip}:6443"),
            encoding="utf-8",
        )


def print_summary(config: Config) -> None:
    print()
    print("Master bootstrap completed.")
    print(f"  project-dir: {config.project_dir}")
    print(f"  node-name: {config.master_node_name}")
    print(f"  node-ip: {config.node_ip}")
    print(f"  advertise-address: {config.advertise_address}")
    print(f"  flannel-iface: {config.flannel_iface}")
    print(f"  monitoring: {'true' if config.install_monitoring else 'false'}")
    print(f"  ingress: {'true' if config.install_ingress else 'false'}")
    print(f"  custom-scaler: {'true' if config.deploy_custom_scaler else 'false'}")


if __name__ == "__main__":
    sys.exit(main())
