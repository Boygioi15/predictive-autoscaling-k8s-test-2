from __future__ import annotations

from functools import lru_cache
from typing import Any

from kubernetes import client, config
from kubernetes.client import ApiException


CUSTOM_SCALER_GROUP = "autoscaling.my.domain"
CUSTOM_SCALER_VERSION = "v1"
CUSTOM_SCALER_PLURAL = "customscalers"


@lru_cache(maxsize=1)
def _load_kubernetes_config() -> None:
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()


class KubernetesGateway:
    def __init__(self) -> None:
        _load_kubernetes_config()
        self._custom = client.CustomObjectsApi()
        self._apps = client.AppsV1Api()
        self._core = client.CoreV1Api()
        self._batch = client.BatchV1Api()

    def list_custom_scalers(self) -> list[dict[str, Any]]:
        payload = self._custom.list_cluster_custom_object(
            group=CUSTOM_SCALER_GROUP,
            version=CUSTOM_SCALER_VERSION,
            plural=CUSTOM_SCALER_PLURAL,
        )
        items = payload.get("items", [])
        return sorted(
            items,
            key=lambda item: (
                item.get("metadata", {}).get("namespace", ""),
                item.get("metadata", {}).get("name", ""),
            ),
        )

    def get_custom_scaler(self, namespace: str, name: str) -> dict[str, Any]:
        return self._custom.get_namespaced_custom_object(
            group=CUSTOM_SCALER_GROUP,
            version=CUSTOM_SCALER_VERSION,
            plural=CUSTOM_SCALER_PLURAL,
            namespace=namespace,
            name=name,
        )

    def read_deployment(self, namespace: str, name: str) -> client.V1Deployment:
        return self._apps.read_namespaced_deployment(name=name, namespace=namespace)

    def list_pods_for_deployment(
        self,
        namespace: str,
        deployment: client.V1Deployment,
    ) -> list[client.V1Pod]:
        selector = deployment.spec.selector.match_labels or {}
        label_selector = ",".join(f"{key}={value}" for key, value in selector.items())
        pod_list = self._core.list_namespaced_pod(namespace=namespace, label_selector=label_selector)
        return sorted(
            pod_list.items,
            key=lambda pod: pod.metadata.name or "",
        )

    def list_managed_worker_nodes(
        self,
        *,
        label_key: str = "",
        label_value: str = "",
    ) -> list[client.V1Node]:
        node_list = self._core.list_node()
        items: list[client.V1Node] = []
        for node in node_list.items:
            labels = node.metadata.labels or {}
            if (
                "node-role.kubernetes.io/control-plane" in labels
                or "node-role.kubernetes.io/master" in labels
            ):
                continue

            if label_key:
                current = labels.get(label_key)
                if current is None:
                    continue
                if label_value and current != label_value:
                    continue

            items.append(node)

        return sorted(items, key=lambda node: node.metadata.name or "")

    def list_worker_jobs(
        self,
        namespace: str,
        *,
        scaler_name: str,
        scaler_namespace: str,
    ) -> list[client.V1Job]:
        label_selector = (
            f"autoscaling.my.domain/customscaler={scaler_name},"
            f"autoscaling.my.domain/scaler-namespace={scaler_namespace}"
        )
        jobs = self._batch.list_namespaced_job(namespace=namespace, label_selector=label_selector)
        return sorted(
            jobs.items,
            key=lambda job: job.metadata.creation_timestamp or 0,
            reverse=True,
        )

    def read_controller_deployment(
        self,
        namespace: str,
        name: str,
    ) -> client.V1Deployment | None:
        try:
            return self._apps.read_namespaced_deployment(name=name, namespace=namespace)
        except ApiException as exc:
            if exc.status == 404:
                return None
            raise
