from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from kubernetes.client import V1Deployment, V1Job

from .kubernetes_client import KubernetesGateway
from .load_test_store import LoadTestStore
from .loop_history_store import LoopHistoryStore
from .script_range_store import ScriptRangeStore
from .settings import Settings, settings


POD_DEFAULT_EXCLUDE_TOKENS = ("WORKER", "NODE_ALLOCATABLE", "POD_REQUEST", "PODS_PER_WORKER")
NODE_DEFAULT_INCLUDE_TOKENS = (
    "WORKER",
    "NODE_ALLOCATABLE",
    "POD_REQUEST",
    "PODS_PER_WORKER",
    "INGRESS_REPLICAS_PER_WORKER",
)
POD_SIGNAL_SPECS: tuple[tuple[str, str, str, str], ...] = (
    ("requests", "RPM", "req/min", "total_requests_per_minute"),
    ("cpu", "CPU", "sec/min", "total_cpu_seconds_per_minute"),
    ("network", "Network", "bytes/min", "total_bandwidth_bytes_per_minute"),
)
POD_LOG_FIELDS: tuple[str, ...] = (
    "forecastContractId",
    "forecastModelName",
    "forecastModelVersion",
    "forecastGeneratedAt",
    "forecastStepSeconds",
    "targetDeployment",
    "peakRequestsPerMinute",
    "effectiveRequestsPerMinute",
    "peakCpuSecondsPerMinute",
    "effectiveCpuSecondsPerMinute",
    "requestReplicaDemand",
    "cpuReplicaDemand",
    "baseReplicaDemand",
    "dominantSignal",
    "currentReplicas",
    "proposedReplicas",
    "desiredReplicas",
    "currentReactivePressureBump",
    "nextReactivePressureBump",
    "reactivePressureReplicaBump",
    "reactivePressureReason",
    "scaleDownAllowed",
    "scaleDownReason",
    "appliedScale",
)
NODE_LOG_FIELDS: tuple[str, ...] = (
    "workerTargetMode",
    "workerCapacityStrategy",
    "targetWorkerCount",
    "rawTargetWorkerCount",
    "desiredReplicas",
    "unschedulablePods",
    "safetyPods",
    "desiredPodsForCapacity",
    "nodeAllocatableMilliCpu",
    "podRequestMilliCpu",
    "podsPerWorker",
    "minWorkerCount",
    "maxWorkerCount",
    "readyWorkerCount",
    "currentAppScheduledPods",
    "totalAppSlotCapacity",
    "missingAppSlots",
    "requiredReadyWorkers",
    "observedReadyWorkers",
    "pendingCreateWorkers",
    "pendingDeleteWorkers",
    "effectiveWorkers",
    "workersToCreate",
    "workersToDelete",
    "lastAction",
    "lastReason",
)


@dataclass(frozen=True)
class WorkloadContext:
    scaler_name: str
    scaler_namespace: str
    deployment_name: str
    controller_namespace: str
    controller_deployment_name: str
    worker_jobs_namespace: str


class SnapshotService:
    def __init__(
        self,
        *,
        config: Settings,
        kubernetes: KubernetesGateway | None = None,
        load_test_store: LoadTestStore | None = None,
        loop_history_store: LoopHistoryStore | None = None,
        script_range_store: ScriptRangeStore | None = None,
    ) -> None:
        self._settings = config
        self._kubernetes = kubernetes or KubernetesGateway()
        self._load_test_store = load_test_store or LoadTestStore(config.load_test_dir)
        self._loop_history_store = loop_history_store or LoopHistoryStore(
            config.load_test_dir,
            limit=config.loop_history_limit,
        )
        self._script_range_store = script_range_store or ScriptRangeStore(config.script_range_csv_path)
        self._cache_lock = asyncio.Lock()
        self._history_lock = asyncio.Lock()
        self._cache: dict[tuple[str, str, int, int], tuple[datetime, dict[str, Any]]] = {}
        self._poller_task: asyncio.Task[None] | None = None
        self._poller_stop: asyncio.Event | None = None

    async def get_snapshot(
        self,
        *,
        force_refresh: bool = False,
        scaler_namespace: str | None = None,
        scaler_name: str | None = None,
        page: int = 1,
        page_size: int = 25,
    ) -> dict[str, Any]:
        namespace = scaler_namespace or self._settings.scaler_namespace
        name = scaler_name or self._settings.scaler_name
        normalized_page = max(page, 1)
        normalized_page_size = min(max(page_size, 1), 100)
        cache_key = (namespace, name, normalized_page, normalized_page_size)

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

            payload = await self._build_snapshot(
                namespace=namespace,
                name=name,
                page=normalized_page,
                page_size=normalized_page_size,
            )
            self._cache[cache_key] = (datetime.now(UTC), payload)
            return payload

    def get_load_test(self) -> dict[str, Any]:
        return self._load_test_store.get_snapshot()

    def save_load_test_script(self, *, filename: str, content: str) -> dict[str, Any]:
        return self._load_test_store.save_script(filename=filename, content=content)

    def save_load_test_metadata(self, metadata: dict[str, Any]) -> dict[str, Any]:
        return self._load_test_store.save_metadata(metadata)

    async def get_script_range(
        self,
        *,
        real_start: datetime | None = None,
        world_cup_start: datetime | None = None,
        duration_seconds: int | None = None,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._script_range_store.get_range,
            real_start=real_start,
            world_cup_start=world_cup_start,
            duration_seconds=duration_seconds,
        )

    async def start_background_poller(self) -> None:
        if self._poller_task is not None and not self._poller_task.done():
            return

        self._poller_stop = asyncio.Event()
        self._poller_task = asyncio.create_task(
            self._run_background_poller(),
            name="system-showcase-history-poller",
        )

    async def stop_background_poller(self) -> None:
        if self._poller_stop is not None:
            self._poller_stop.set()

        if self._poller_task is not None:
            await self._poller_task

        self._poller_task = None
        self._poller_stop = None

    async def _run_background_poller(self) -> None:
        stop_event = self._poller_stop
        if stop_event is None:
            return

        while not stop_event.is_set():
            try:
                await self.poll_history_once()
            except Exception:
                pass

            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=self._settings.background_poll_interval_seconds,
                )
            except TimeoutError:
                continue

    async def poll_history_once(self) -> bool:
        try:
            scaler_items = await asyncio.to_thread(self._kubernetes.list_custom_scalers)
        except Exception:
            return False

        changed = False
        async with self._history_lock:
            for scaler in scaler_items:
                metadata = scaler.get("metadata", {})
                status = scaler.get("status", {})
                scaler_key = f"{metadata.get('namespace', self._settings.scaler_namespace)}/{metadata.get('name', self._settings.scaler_name)}"
                result = self._loop_history_store.sync_latest(
                    scaler_key=scaler_key,
                    pod_loop=self._normalize_pod_loop(status.get("lastPodLoop")),
                    node_loop=self._normalize_node_loop(status.get("lastNodeLoop")),
                )
                if result.get("changed"):
                    changed = True

        if changed:
            async with self._cache_lock:
                self._cache.clear()

        return changed

    async def _build_snapshot(
        self,
        *,
        namespace: str,
        name: str,
        page: int,
        page_size: int,
    ) -> dict[str, Any]:
        errors: list[dict[str, str]] = []
        available_scalers: list[dict[str, Any]] = []
        generated_at = datetime.now(UTC).isoformat()
        scaler_key = f"{namespace}/{name}"

        try:
            scaler_items = await asyncio.to_thread(self._kubernetes.list_custom_scalers)
            available_scalers = [self._scaler_summary(item) for item in scaler_items]
        except Exception as exc:  # pragma: no cover - defensive
            errors.append({"source": "kubernetes.customscalers", "message": str(exc)})
            scaler_items = []

        active_scaler = self._choose_scaler(scaler_items, namespace=namespace, name=name)
        if active_scaler is None:
            async with self._history_lock:
                empty_history = self._loop_history_store.get_snapshot(scaler_key=scaler_key)
            paginated_history = self._paginate_minute_groups(
                empty_history["podLoops"],
                empty_history["nodeLoops"],
                page=page,
                page_size=page_size,
            )
            return {
                "generatedAt": generated_at,
                "basePath": self._settings.normalized_base_path,
                "cacheTtlSeconds": self._settings.cache_ttl_seconds,
                "availableScalers": available_scalers,
                "activeScaler": None,
                "controller": {
                    "latest": {"podLoop": None, "nodeLoop": None},
                    "historyLimit": empty_history["limit"],
                    "historyCounts": {
                        "podLoops": len(empty_history["podLoops"]),
                        "nodeLoops": len(empty_history["nodeLoops"]),
                        "minuteGroups": paginated_history["totalItems"],
                    },
                    "minuteGroups": paginated_history["items"],
                    "recentMinuteGroups": paginated_history["recentItems"],
                    "pagination": paginated_history["pagination"],
                    "sidebar": {
                        "podConfig": {"spec": {}, "status": {}, "defaults": {}},
                        "nodeConfig": {"spec": {}, "status": {}, "defaults": {}},
                        "jobStatus": [],
                    },
                },
                "errors": errors + [
                    {
                        "source": "kubernetes.customscalers",
                        "message": "No CustomScaler resource was found.",
                    }
                ],
            }

        context = self._context_from_scaler(active_scaler)
        controller_deployment_task = asyncio.to_thread(
            self._kubernetes.read_controller_deployment,
            context.controller_namespace,
            context.controller_deployment_name,
        )
        jobs_task = asyncio.to_thread(
            self._kubernetes.list_worker_jobs,
            context.worker_jobs_namespace,
            scaler_name=context.scaler_name,
            scaler_namespace=context.scaler_namespace,
        )

        controller_deployment, jobs = await asyncio.gather(
            self._capture("kubernetes.controllerDeployment", controller_deployment_task, errors),
            self._capture("kubernetes.jobs", jobs_task, errors, default=[]),
        )

        controller_env = self._extract_controller_env(controller_deployment)
        pod_defaults, node_defaults = self._split_controller_defaults(controller_env)
        scaler_spec = active_scaler.get("spec", {})
        scaler_status = active_scaler.get("status", {})

        latest_pod_loop = self._normalize_pod_loop(scaler_status.get("lastPodLoop"))
        latest_node_loop = self._normalize_node_loop(scaler_status.get("lastNodeLoop"))
        async with self._history_lock:
            history = self._loop_history_store.sync_latest(
                scaler_key=f"{context.scaler_namespace}/{context.scaler_name}",
                pod_loop=latest_pod_loop,
                node_loop=latest_node_loop,
            )
        paginated_history = self._paginate_minute_groups(
            history["podLoops"],
            history["nodeLoops"],
            page=page,
            page_size=page_size,
        )

        return {
            "generatedAt": generated_at,
            "basePath": self._settings.normalized_base_path,
            "cacheTtlSeconds": self._settings.cache_ttl_seconds,
            "availableScalers": available_scalers,
            "activeScaler": {
                "name": active_scaler["metadata"]["name"],
                "namespace": active_scaler["metadata"]["namespace"],
                "spec": scaler_spec,
                "status": scaler_status,
            },
            "controller": {
                "latest": {
                    "podLoop": latest_pod_loop,
                    "nodeLoop": latest_node_loop,
                },
                "historyLimit": history["limit"],
                "historyCounts": {
                    "podLoops": len(history["podLoops"]),
                    "nodeLoops": len(history["nodeLoops"]),
                    "minuteGroups": paginated_history["totalItems"],
                },
                "minuteGroups": paginated_history["items"],
                "recentMinuteGroups": paginated_history["recentItems"],
                "pagination": paginated_history["pagination"],
                "sidebar": {
                    "podConfig": {
                        "spec": self._pod_config_spec(scaler_spec),
                        "status": self._pod_config_status(scaler_status),
                        "defaults": pod_defaults,
                    },
                    "nodeConfig": {
                        "spec": self._node_config_spec(scaler_spec),
                        "status": self._node_config_status(scaler_status, latest_node_loop),
                        "defaults": node_defaults,
                    },
                    "jobStatus": [self._serialize_job(job) for job in jobs[:24]],
                },
            },
            "errors": errors,
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
        return WorkloadContext(
            scaler_name=metadata.get("name", self._settings.scaler_name),
            scaler_namespace=metadata.get("namespace", self._settings.scaler_namespace),
            deployment_name=spec.get("deploymentName") or "demo-app-deployment",
            controller_namespace=self._settings.controller_namespace,
            controller_deployment_name=self._settings.controller_deployment_name,
            worker_jobs_namespace=self._settings.worker_jobs_namespace,
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

    def _split_controller_defaults(self, env_map: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
        pod_defaults: dict[str, str] = {}
        node_defaults: dict[str, str] = {}

        for key, value in env_map.items():
            if any(token in key for token in NODE_DEFAULT_INCLUDE_TOKENS):
                node_defaults[key] = value
            elif not any(token in key for token in POD_DEFAULT_EXCLUDE_TOKENS):
                pod_defaults[key] = value
            else:
                node_defaults[key] = value

        return pod_defaults, node_defaults

    def _normalize_pod_loop(self, payload: dict[str, Any] | None) -> dict[str, Any] | None:
        if payload is None:
            return None

        normalized = dict(payload)
        if "appliedScale" not in normalized:
            normalized["appliedScale"] = False
        request_body = self._parse_json_string(payload.get("forecastRequestPayload"))
        response_body = self._parse_json_string(payload.get("forecastResponseBody"))
        history = self._extract_response_history(response_body)
        if not history:
            history = self._extract_input_history(request_body)
        if not history and isinstance(response_body, dict):
            history = response_body.get("history", {}) or {}
        observed = response_body.get("observed", {}) if isinstance(response_body, dict) else {}
        prediction_rows = response_body.get("prediction_rows", []) if isinstance(response_body, dict) else []
        prediction_values = response_body.get("predictions", []) if isinstance(response_body, dict) else []
        observed_at = str(payload.get("observedAt") or "")

        normalized["loopKey"] = self._build_loop_key("pod", observed_at, payload.get("desiredReplicas"))
        normalized["minuteBucket"] = self._minute_bucket(observed_at)
        normalized["signals"] = [
            self._build_pod_signal(
                signal_id=signal_id,
                label=label,
                unit=unit,
                metric_key=metric_key,
                history=history,
                observed=observed,
                prediction_rows=prediction_rows,
                request_predictions=prediction_values,
            )
            for signal_id, label, unit, metric_key in POD_SIGNAL_SPECS
        ]
        normalized["logFields"] = self._ordered_log_fields(normalized, POD_LOG_FIELDS)
        normalized.pop("forecastRequestPayload", None)
        normalized.pop("forecastResponseBody", None)
        return normalized

    def _normalize_node_loop(self, payload: dict[str, Any] | None) -> dict[str, Any] | None:
        if payload is None:
            return None

        normalized = dict(payload)
        observed_at = str(payload.get("observedAt") or "")
        normalized["loopKey"] = self._build_loop_key(
            "node",
            observed_at,
            payload.get("targetWorkerCount"),
        )
        normalized["minuteBucket"] = self._minute_bucket(observed_at)
        normalized["logFields"] = self._ordered_log_fields(normalized, NODE_LOG_FIELDS)
        normalized["activeOperations"] = payload.get("activeOperations") or []
        return normalized

    def _build_pod_signal(
        self,
        *,
        signal_id: str,
        label: str,
        unit: str,
        metric_key: str,
        history: dict[str, Any],
        observed: dict[str, Any],
        prediction_rows: list[dict[str, Any]],
        request_predictions: list[Any],
    ) -> dict[str, Any]:
        prediction_rows_source = [
            row.get(metric_key)
            for row in prediction_rows
            if isinstance(row, dict) and metric_key in row
        ]

        input_source = history.get(metric_key)
        if input_source is None:
            input_source = observed.get(metric_key)

        if metric_key == "total_requests_per_minute":
            prediction_source = prediction_rows_source or request_predictions
        else:
            prediction_source = prediction_rows_source

        input_points = self._downsample_numeric_series(input_source, max_points=60)
        prediction_points = self._downsample_numeric_series(prediction_source, max_points=20)
        return {
            "id": signal_id,
            "label": label,
            "unit": unit,
            "input": input_points,
            "prediction": prediction_points,
            "inputLast": input_points[-1] if input_points else None,
            "predictionLast": prediction_points[-1] if prediction_points else None,
            "predictionPeak": max(prediction_points) if prediction_points else None,
        }

    def _extract_input_history(self, request_body: Any) -> dict[str, list[float]]:
        if not isinstance(request_body, dict):
            return {}

        raw_history = request_body.get("history")
        if isinstance(raw_history, dict):
            return {
                key: self._downsample_numeric_series(values, max_points=10_000)
                for key, values in raw_history.items()
                if isinstance(values, list)
            }

        if not isinstance(raw_history, list):
            return {}

        extracted: dict[str, list[float]] = {}
        for metric_key in (
            "total_requests_per_minute",
            "total_cpu_seconds_per_minute",
            "total_bandwidth_bytes_per_minute",
        ):
            extracted[metric_key] = self._downsample_numeric_series(
                [
                    row.get(metric_key)
                    for row in raw_history
                    if isinstance(row, dict) and metric_key in row
                ],
                max_points=10_000,
            )
        return extracted

    def _extract_response_history(self, response_body: Any) -> dict[str, list[float]]:
        if not isinstance(response_body, dict):
            return {}

        if isinstance(response_body.get("history"), dict):
            return {
                key: self._downsample_numeric_series(values, max_points=10_000)
                for key, values in response_body["history"].items()
                if isinstance(values, list)
            }

        raw_history_rows = response_body.get("history_rows")
        if not isinstance(raw_history_rows, list):
            return {}

        extracted: dict[str, list[float]] = {}
        for metric_key in (
            "total_requests_per_minute",
            "total_cpu_seconds_per_minute",
            "total_bandwidth_bytes_per_minute",
        ):
            extracted[metric_key] = self._downsample_numeric_series(
                [
                    row.get(metric_key)
                    for row in raw_history_rows
                    if isinstance(row, dict) and metric_key in row
                ],
                max_points=10_000,
            )
        return extracted

    def _ordered_log_fields(
        self,
        payload: dict[str, Any],
        ordered_keys: tuple[str, ...],
    ) -> list[dict[str, Any]]:
        fields: list[dict[str, Any]] = []
        for key in ordered_keys:
            if key not in payload:
                continue
            fields.append(
                {
                    "key": key,
                    "label": key,
                    "value": payload.get(key),
                }
            )
        return fields

    def _parse_json_string(self, value: Any) -> Any:
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value

    def _downsample_numeric_series(
        self,
        values: Any,
        *,
        max_points: int = 24,
    ) -> list[float]:
        if not isinstance(values, list):
            return []

        numeric_values: list[float] = []
        for item in values:
            if item is None:
                continue
            try:
                numeric_values.append(float(item))
            except (TypeError, ValueError):
                continue

        if len(numeric_values) <= max_points:
            return numeric_values

        result: list[float] = []
        last_index = len(numeric_values) - 1
        for point_index in range(max_points):
            raw_index = round((point_index / max(max_points - 1, 1)) * last_index)
            result.append(numeric_values[raw_index])
        return result

    def _build_loop_key(self, prefix: str, observed_at: str, fallback_value: Any) -> str:
        return f"{prefix}:{observed_at or 'unknown'}:{fallback_value if fallback_value is not None else 'none'}"

    def _minute_bucket(self, value: str) -> str:
        if not value:
            return "unknown"

        try:
            normalized = value.replace("Z", "+00:00")
            dt = datetime.fromisoformat(normalized)
        except ValueError:
            return value[:16]

        return dt.astimezone(UTC).replace(second=0, microsecond=0).isoformat()

    def _paginate_minute_groups(
        self,
        pod_loops: list[dict[str, Any]],
        node_loops: list[dict[str, Any]],
        *,
        page: int,
        page_size: int,
    ) -> dict[str, Any]:
        grouped_pod_loops: dict[str, list[dict[str, Any]]] = {}
        grouped_node_loops: dict[str, list[dict[str, Any]]] = {}

        for loop in reversed(pod_loops):
            bucket = str(loop.get("minuteBucket") or "unknown")
            grouped_pod_loops.setdefault(bucket, []).append(loop)

        for loop in reversed(node_loops):
            bucket = str(loop.get("minuteBucket") or "unknown")
            grouped_node_loops.setdefault(bucket, []).append(loop)

        ordered_keys = sorted(
            set(grouped_pod_loops) | set(grouped_node_loops),
            reverse=True,
        )
        total_items = len(ordered_keys)
        total_pages = max((total_items + page_size - 1) // page_size, 1)
        current_page = min(max(page, 1), total_pages)
        start_index = (current_page - 1) * page_size
        end_index = min(start_index + page_size, total_items)

        def build_group(bucket: str) -> dict[str, Any]:
            return {
                "groupKey": bucket,
                "minuteBucket": bucket,
                "podLoops": grouped_pod_loops.get(bucket, []),
                "nodeLoops": grouped_node_loops.get(bucket, []),
            }

        return {
            "items": [build_group(bucket) for bucket in ordered_keys[start_index:end_index]],
            "recentItems": [build_group(bucket) for bucket in ordered_keys[:16]],
            "totalItems": total_items,
            "pagination": {
                "page": current_page,
                "pageSize": page_size,
                "totalItems": total_items,
                "totalPages": total_pages,
                "hasPreviousPage": current_page > 1,
                "hasNextPage": current_page < total_pages,
                "startItem": start_index + 1 if total_items else 0,
                "endItem": end_index,
            },
        }

    def _pod_config_spec(self, spec: dict[str, Any]) -> dict[str, Any]:
        return {
            "url": spec.get("url"),
            "deploymentName": spec.get("deploymentName"),
            "forecastDeployment": spec.get("forecastDeployment"),
            "intervalMinutes": spec.get("intervalMinutes"),
            "requestsPerPod": spec.get("requestsPerPod"),
            "safetyFactor": spec.get("safetyFactor"),
            "sparePod": spec.get("sparePod"),
            "minReplicas": spec.get("minReplicas"),
            "maxReplicas": spec.get("maxReplicas"),
        }

    def _pod_config_status(self, status: dict[str, Any]) -> dict[str, Any]:
        return {
            "lastForecastPeak": status.get("lastForecastPeak"),
            "lastEffectiveRequestsPerMinute": status.get("lastEffectiveRequestsPerMinute"),
            "lastDesiredReplicas": status.get("lastDesiredReplicas"),
            "currentReplicas": status.get("currentReplicas"),
            "reactivePressureBump": status.get("reactivePressureBump"),
            "reactivePressureReason": status.get("reactivePressureReason"),
        }

    def _node_config_spec(self, spec: dict[str, Any]) -> dict[str, Any]:
        worker_spec = spec.get("workerPrototype") or {}
        return {
            "targetWorkerCount": worker_spec.get("targetWorkerCount"),
            "maxBatchSize": worker_spec.get("maxBatchSize"),
            "nodeLabelKey": worker_spec.get("nodeLabelKey"),
            "nodeLabelValue": worker_spec.get("nodeLabelValue"),
        }

    def _node_config_status(
        self,
        status: dict[str, Any],
        latest_node_loop: dict[str, Any] | None,
    ) -> dict[str, Any]:
        worker_status = status.get("workerPrototype") or {}
        return {
            "targetWorkerCount": worker_status.get("targetWorkerCount"),
            "observedReadyWorkerCount": worker_status.get("observedReadyWorkerCount"),
            "pendingCreateCount": worker_status.get("pendingCreateCount"),
            "pendingDeleteCount": worker_status.get("pendingDeleteCount"),
            "effectiveWorkerCount": worker_status.get("effectiveWorkerCount"),
            "lastAction": worker_status.get("lastAction") or (latest_node_loop or {}).get("lastAction"),
            "lastReason": worker_status.get("lastReason") or (latest_node_loop or {}).get("lastReason"),
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


snapshot_service = SnapshotService(config=settings)
