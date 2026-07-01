from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from kubernetes.client import V1Deployment, V1Job, V1Node, V1Pod

from .kubernetes_client import KubernetesGateway
from .load_test_store import LoadTestStore
from .prometheus_client import PrometheusClient
from .settings import Settings, settings


@dataclass(frozen=True)
class MetricDefinition:
    key: str
    title: str
    unit: str
    query_template: str
    description: str


@dataclass(frozen=True)
class WorkloadContext:
    scaler_name: str
    scaler_namespace: str
    deployment_name: str
    app_namespace: str
    app_service_name: str
    app_ingress_name: str
    app_pod_regex: str
    controller_namespace: str
    controller_deployment_name: str
    worker_jobs_namespace: str
    worker_node_label_key: str
    worker_node_label_value: str

    @property
    def base_workload_name(self) -> str:
        if self.deployment_name.endswith("-deployment"):
            return self.deployment_name[: -len("-deployment")]
        return self.deployment_name


METRICS: tuple[MetricDefinition, ...] = (
    MetricDefinition(
        key="ingress_rps",
        title="Ingress RPS",
        unit="rps",
        query_template='sum(rate(nginx_ingress_controller_requests{{ingress="{app_ingress_name}"}}[1m]))',
        description="Requests per second observed at the ingress layer.",
    ),
    MetricDefinition(
        key="app_rps",
        title="App RPS",
        unit="rps",
        query_template='sum(rate(http_request_duration_seconds_count{{service="{app_service_name}"}}[1m]))',
        description="Requests per second seen by the demo app metrics middleware.",
    ),
    MetricDefinition(
        key="cpu_usage",
        title="CPU Usage",
        unit="cores",
        query_template=(
            'sum(rate(container_cpu_usage_seconds_total{{namespace="{app_namespace}",'
            'pod=~"{app_pod_regex}",container!="POD",container!=""}}[1m]))'
        ),
        description="Aggregate CPU usage rate across demo app pods.",
    ),
    MetricDefinition(
        key="memory_usage",
        title="Memory Usage",
        unit="MB",
        query_template=(
            'sum(container_memory_usage_bytes{{namespace="{app_namespace}",pod=~"{app_pod_regex}",'
            'container!=""}})/(1024*1024)'
        ),
        description="Aggregate memory usage across demo app pods.",
    ),
    MetricDefinition(
        key="pod_count",
        title="Pod Count",
        unit="count",
        query_template='count(kube_pod_info{{namespace="{app_namespace}",pod=~"{app_pod_regex}"}})',
        description="Current number of demo app pods.",
    ),
    MetricDefinition(
        key="node_count",
        title="Node Count",
        unit="count",
        query_template="count(kube_node_info)",
        description="Total nodes visible to the cluster.",
    ),
    MetricDefinition(
        key="ingress_p99",
        title="Ingress P99",
        unit="seconds",
        query_template=(
            'histogram_quantile(0.99, sum by (le) '
            '(rate(nginx_ingress_controller_request_duration_seconds_bucket{{ingress="{app_ingress_name}"}}[1m])))'
        ),
        description="Ingress p99 latency over the last minute.",
    ),
    MetricDefinition(
        key="app_p99",
        title="App P99",
        unit="seconds",
        query_template=(
            'histogram_quantile(0.99, sum by (le) '
            '(rate(http_request_duration_seconds_bucket{{service="{app_service_name}",status!~"5.."}}[1m])))'
        ),
        description="Application p99 latency for non-5xx responses.",
    ),
    MetricDefinition(
        key="app_error_rate",
        title="App Error Rate",
        unit="ratio",
        query_template=(
            '((sum(increase(http_requests_total{{service="{app_service_name}",status=~"5.."}}[1m])) or on() vector(0)) '
            '/ clamp_min((sum(increase(http_requests_total{{service="{app_service_name}"}}[1m])) or on() vector(0)), 1))'
        ),
        description="Application 5xx error rate over the last minute.",
    ),
    MetricDefinition(
        key="nginx_connections",
        title="Nginx Connections",
        unit="count",
        query_template='sum(nginx_ingress_controller_nginx_process_connections{{state=~"active|writing"}})',
        description="Aggregate active and writing nginx ingress connections.",
    ),
)


class SnapshotService:
    def __init__(
        self,
        *,
        config: Settings,
        prometheus: PrometheusClient | None = None,
        kubernetes: KubernetesGateway | None = None,
        load_test_store: LoadTestStore | None = None,
    ) -> None:
        self._settings = config
        self._prometheus = prometheus or PrometheusClient()
        self._kubernetes = kubernetes or KubernetesGateway()
        self._load_test_store = load_test_store or LoadTestStore(config.load_test_dir)
        self._cache_lock = asyncio.Lock()
        self._cache: dict[tuple[str, str], tuple[datetime, dict[str, Any]]] = {}

    async def get_snapshot(
        self,
        *,
        force_refresh: bool = False,
        scaler_namespace: str | None = None,
        scaler_name: str | None = None,
    ) -> dict[str, Any]:
        namespace = scaler_namespace or self._settings.scaler_namespace
        name = scaler_name or self._settings.scaler_name
        cache_key = (namespace, name)

        if not force_refresh:
            cached = self._cache.get(cache_key)
            if cached is not None:
                cached_at, payload = cached
                if datetime.now(UTC) - cached_at < timedelta(seconds=self._settings.cache_ttl_seconds):
                    return payload

        async with self._cache_lock:
            if not force_refresh:
                cached = self._cache.get(cache_key)
                if cached is not None:
                    cached_at, payload = cached
                    if datetime.now(UTC) - cached_at < timedelta(seconds=self._settings.cache_ttl_seconds):
                        return payload

            payload = await self._build_snapshot(namespace=namespace, name=name)
            self._cache[cache_key] = (datetime.now(UTC), payload)
            return payload

    def get_load_test(self) -> dict[str, Any]:
        return self._load_test_store.get_snapshot()

    def save_load_test_script(self, *, filename: str, content: str) -> dict[str, Any]:
        return self._load_test_store.save_script(filename=filename, content=content)

    def save_load_test_metadata(self, metadata: dict[str, Any]) -> dict[str, Any]:
        return self._load_test_store.save_metadata(metadata)

    async def _build_snapshot(self, *, namespace: str, name: str) -> dict[str, Any]:
        errors: list[dict[str, str]] = []
        available_scalers: list[dict[str, Any]] = []

        try:
            scaler_items = await asyncio.to_thread(self._kubernetes.list_custom_scalers)
            available_scalers = [self._scaler_summary(item) for item in scaler_items]
        except Exception as exc:  # pragma: no cover - defensive
            errors.append({"source": "kubernetes.customscalers", "message": str(exc)})
            scaler_items = []

        active_scaler = self._choose_scaler(scaler_items, namespace=namespace, name=name)
        load_test = self._load_test_store.get_snapshot()
        generated_at = datetime.now(UTC).isoformat()

        if active_scaler is None:
            return {
                "generatedAt": generated_at,
                "basePath": self._settings.normalized_base_path,
                "cacheTtlSeconds": self._settings.cache_ttl_seconds,
                "availableScalers": available_scalers,
                "activeScaler": None,
                "system": {"cards": [], "charts": []},
                "controller": {"policyDefaults": {}, "podLoop": None, "nodeLoop": None},
                "resources": {"deployment": None, "pods": {"counts": {}, "items": []}, "workerNodes": {"counts": {}, "items": []}, "jobs": []},
                "loadTest": load_test,
                "errors": errors + [{"source": "kubernetes.customscalers", "message": "No CustomScaler resource was found."}],
            }

        context = self._context_from_scaler(active_scaler)

        deployment_task = asyncio.to_thread(
            self._kubernetes.read_deployment,
            context.scaler_namespace,
            context.deployment_name,
        )
        controller_deployment_task = asyncio.to_thread(
            self._kubernetes.read_controller_deployment,
            context.controller_namespace,
            context.controller_deployment_name,
        )
        worker_nodes_task = asyncio.to_thread(
            self._kubernetes.list_managed_worker_nodes,
            label_key=context.worker_node_label_key,
            label_value=context.worker_node_label_value,
        )
        jobs_task = asyncio.to_thread(
            self._kubernetes.list_worker_jobs,
            context.worker_jobs_namespace,
            scaler_name=context.scaler_name,
            scaler_namespace=context.scaler_namespace,
        )
        metrics_task = self._build_metrics(context)

        deployment_result, controller_deployment, worker_nodes, jobs, metrics_payload = await asyncio.gather(
            self._capture("kubernetes.deployment", deployment_task, errors),
            self._capture("kubernetes.controllerDeployment", controller_deployment_task, errors),
            self._capture("kubernetes.workerNodes", worker_nodes_task, errors, default=[]),
            self._capture("kubernetes.jobs", jobs_task, errors, default=[]),
            self._capture("prometheus.metrics", metrics_task, errors, default={"cards": [], "charts": []}),
        )

        app_pods: list[V1Pod] = []
        if deployment_result is not None:
            app_pods = await self._capture(
                "kubernetes.pods",
                asyncio.to_thread(
                    self._kubernetes.list_pods_for_deployment,
                    context.scaler_namespace,
                    deployment_result,
                ),
                errors,
                default=[],
            )

        controller_env = self._extract_controller_env(controller_deployment)

        return {
            "generatedAt": generated_at,
            "basePath": self._settings.normalized_base_path,
            "cacheTtlSeconds": self._settings.cache_ttl_seconds,
            "availableScalers": available_scalers,
            "activeScaler": {
                "name": active_scaler["metadata"]["name"],
                "namespace": active_scaler["metadata"]["namespace"],
                "spec": active_scaler.get("spec", {}),
                "status": active_scaler.get("status", {}),
            },
            "system": metrics_payload,
            "controller": {
                "policyDefaults": controller_env,
                "controllerDeployment": self._serialize_deployment(controller_deployment) if controller_deployment else None,
                "podLoop": self._normalize_pod_loop(active_scaler.get("status", {}).get("lastPodLoop")),
                "nodeLoop": active_scaler.get("status", {}).get("lastNodeLoop"),
            },
            "resources": {
                "deployment": self._serialize_deployment(deployment_result) if deployment_result else None,
                "pods": self._serialize_pods(app_pods),
                "workerNodes": self._serialize_nodes(worker_nodes),
                "jobs": [self._serialize_job(job) for job in jobs[:12]],
            },
            "loadTest": load_test,
            "errors": errors,
        }

    async def _build_metrics(self, context: WorkloadContext) -> dict[str, Any]:
        end = datetime.now(UTC)
        start = end - timedelta(minutes=self._settings.metrics_window_minutes)

        async def build_metric(metric: MetricDefinition) -> dict[str, Any]:
            query = metric.query_template.format(
                app_namespace=context.app_namespace,
                app_service_name=context.app_service_name,
                app_ingress_name=context.app_ingress_name,
                app_pod_regex=context.app_pod_regex,
            )
            try:
                series = await self._prometheus.query_range(
                    query,
                    start=start,
                    end=end,
                    step_seconds=self._settings.metrics_step_seconds,
                )
                points = [
                    {"timestamp": point.timestamp, "value": point.value}
                    for series_item in series
                    for point in series_item.points
                ]
                current = points[-1]["value"] if points else 0.0
                return {
                    "id": metric.key,
                    "title": metric.title,
                    "unit": metric.unit,
                    "description": metric.description,
                    "query": query,
                    "currentValue": current,
                    "series": [
                        {
                            "name": series_item.name,
                            "points": [{"timestamp": point.timestamp, "value": point.value} for point in series_item.points],
                        }
                        for series_item in series
                    ],
                    "error": None,
                }
            except Exception as exc:
                return {
                    "id": metric.key,
                    "title": metric.title,
                    "unit": metric.unit,
                    "description": metric.description,
                    "query": query,
                    "currentValue": None,
                    "series": [],
                    "error": str(exc),
                }

        charts = await asyncio.gather(*(build_metric(metric) for metric in METRICS))
        cards = [
            {
                "id": chart["id"],
                "title": chart["title"],
                "unit": chart["unit"],
                "description": chart["description"],
                "value": chart["currentValue"],
            }
            for chart in charts
        ]
        return {
            "cards": cards,
            "charts": charts,
        }

    async def _capture(
        self,
        source: str,
        awaitable: Any,
        errors: list[dict[str, str]],
        *,
        default: Any = None,
    ) -> Any:
        try:
            return await awaitable
        except Exception as exc:  # pragma: no cover - defensive
            errors.append({"source": source, "message": str(exc)})
            return default

    def _choose_scaler(
        self,
        items: list[dict[str, Any]],
        *,
        namespace: str,
        name: str,
    ) -> dict[str, Any] | None:
        for item in items:
            metadata = item.get("metadata", {})
            if metadata.get("namespace") == namespace and metadata.get("name") == name:
                return item
        return items[0] if items else None

    def _scaler_summary(self, scaler: dict[str, Any]) -> dict[str, Any]:
        metadata = scaler.get("metadata", {})
        spec = scaler.get("spec", {})
        return {
            "name": metadata.get("name", ""),
            "namespace": metadata.get("namespace", ""),
            "deploymentName": spec.get("deploymentName", ""),
        }

    def _context_from_scaler(self, scaler: dict[str, Any]) -> WorkloadContext:
        metadata = scaler.get("metadata", {})
        spec = scaler.get("spec", {})
        worker_spec = spec.get("workerPrototype") or {}

        deployment_name = spec.get("deploymentName") or "demo-app-deployment"
        base_name = deployment_name[: -len("-deployment")] if deployment_name.endswith("-deployment") else deployment_name
        app_namespace = metadata.get("namespace") or self._settings.app_namespace

        service_name = self._settings.app_service_name or f"{base_name}-svc"
        ingress_name = self._settings.app_ingress_name or f"{base_name}-ingress"
        pod_regex = self._settings.app_pod_regex or f"{deployment_name}-.*"

        return WorkloadContext(
            scaler_name=metadata.get("name", self._settings.scaler_name),
            scaler_namespace=metadata.get("namespace", self._settings.scaler_namespace),
            deployment_name=deployment_name,
            app_namespace=app_namespace,
            app_service_name=service_name,
            app_ingress_name=ingress_name,
            app_pod_regex=pod_regex,
            controller_namespace=self._settings.controller_namespace,
            controller_deployment_name=self._settings.controller_deployment_name,
            worker_jobs_namespace=self._settings.worker_jobs_namespace,
            worker_node_label_key=worker_spec.get("nodeLabelKey", ""),
            worker_node_label_value=worker_spec.get("nodeLabelValue", ""),
        )

    def _extract_controller_env(self, deployment: V1Deployment | None) -> dict[str, str]:
        if deployment is None or not deployment.spec.template.spec.containers:
            return {}

        env_map: dict[str, str] = {}
        container = deployment.spec.template.spec.containers[0]
        for env_var in container.env or []:
            if env_var.name.startswith("SCALER_"):
                env_map[env_var.name] = env_var.value or ""
        return dict(sorted(env_map.items()))

    def _normalize_pod_loop(self, payload: dict[str, Any] | None) -> dict[str, Any] | None:
        if payload is None:
            return None

        normalized = dict(payload)
        normalized["forecastRequestPayloadJson"] = self._parse_json_string(payload.get("forecastRequestPayload"))
        normalized["forecastResponseBodyJson"] = self._parse_json_string(payload.get("forecastResponseBody"))
        return normalized

    def _parse_json_string(self, value: Any) -> Any:
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value

    def _serialize_deployment(self, deployment: V1Deployment | None) -> dict[str, Any] | None:
        if deployment is None:
            return None

        status = deployment.status
        spec = deployment.spec
        return {
            "name": deployment.metadata.name,
            "namespace": deployment.metadata.namespace,
            "images": [container.image for container in spec.template.spec.containers],
            "selector": spec.selector.match_labels or {},
            "desiredReplicas": spec.replicas or 0,
            "readyReplicas": status.ready_replicas or 0,
            "availableReplicas": status.available_replicas or 0,
            "updatedReplicas": status.updated_replicas or 0,
            "observedGeneration": status.observed_generation or 0,
            "conditions": [
                {
                    "type": condition.type,
                    "status": condition.status,
                    "reason": condition.reason,
                    "message": condition.message,
                }
                for condition in status.conditions or []
            ],
        }

    def _serialize_pods(self, pods: list[V1Pod]) -> dict[str, Any]:
        items = [self._serialize_pod(pod) for pod in pods]
        ready_count = sum(1 for item in items if item["ready"])
        phases: dict[str, int] = {}
        for item in items:
            phases[item["phase"]] = phases.get(item["phase"], 0) + 1
        return {
            "counts": {
                "total": len(items),
                "ready": ready_count,
                "notReady": max(len(items) - ready_count, 0),
                "phases": phases,
            },
            "items": items,
        }

    def _serialize_pod(self, pod: V1Pod) -> dict[str, Any]:
        statuses = pod.status.container_statuses or []
        ready_containers = sum(1 for status in statuses if status.ready)
        restart_count = sum(status.restart_count for status in statuses)
        return {
            "name": pod.metadata.name,
            "phase": pod.status.phase or "Unknown",
            "nodeName": pod.spec.node_name or "",
            "podIP": pod.status.pod_ip or "",
            "ready": all(status.ready for status in statuses) if statuses else False,
            "readyContainers": ready_containers,
            "containerCount": len(statuses),
            "restartCount": restart_count,
            "qosClass": pod.status.qos_class or "",
            "createdAt": pod.metadata.creation_timestamp.isoformat() if pod.metadata.creation_timestamp else "",
        }

    def _serialize_nodes(self, nodes: list[V1Node]) -> dict[str, Any]:
        items = [self._serialize_node(node) for node in nodes]
        ready_count = sum(1 for item in items if item["ready"])
        return {
            "counts": {
                "total": len(items),
                "ready": ready_count,
                "notReady": max(len(items) - ready_count, 0),
            },
            "items": items,
        }

    def _serialize_node(self, node: V1Node) -> dict[str, Any]:
        labels = node.metadata.labels or {}
        roles = sorted(
            key.split("/", 1)[1]
            for key in labels
            if key.startswith("node-role.kubernetes.io/")
        )
        allocatable = node.status.allocatable or {}
        alloc_cpu = allocatable.get("cpu")
        alloc_mem = allocatable.get("memory")
        return {
            "name": node.metadata.name,
            "ready": self._node_ready(node),
            "roles": roles,
            "allocatableCpu": alloc_cpu,
            "allocatableMemory": alloc_mem,
            "labels": {key: value for key, value in labels.items() if key.startswith("node-role.kubernetes.io/") or key == "role"},
            "createdAt": node.metadata.creation_timestamp.isoformat() if node.metadata.creation_timestamp else "",
        }

    def _serialize_job(self, job: V1Job) -> dict[str, Any]:
        labels = job.metadata.labels or {}
        status = job.status
        return {
            "name": job.metadata.name,
            "namespace": job.metadata.namespace,
            "operationType": labels.get("autoscaling.my.domain/worker-op", ""),
            "active": status.active or 0,
            "succeeded": status.succeeded or 0,
            "failed": status.failed or 0,
            "startTime": status.start_time.isoformat() if status.start_time else "",
            "completionTime": status.completion_time.isoformat() if status.completion_time else "",
            "conditions": [
                {
                    "type": condition.type,
                    "status": condition.status,
                    "reason": condition.reason,
                    "message": condition.message,
                }
                for condition in status.conditions or []
            ],
        }

    def _node_ready(self, node: V1Node) -> bool:
        for condition in node.status.conditions or []:
            if condition.type == "Ready":
                return condition.status == "True"
        return False


snapshot_service = SnapshotService(config=settings)
