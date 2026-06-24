from __future__ import annotations

import asyncio
import csv
import json
import logging
import os
import signal
import subprocess
import sys
import time
from collections import deque
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import aiohttp

from workload import REQUEST_CLASS_COLUMNS, PreparedRequest, WorkloadPlanner, load_workload_config

logger = logging.getLogger("custom_load_generator")


@dataclass(frozen=True)
class ScriptPoint:
    timestamp: datetime
    requests: int
    request_class_counts: tuple[int, ...]


@dataclass(frozen=True)
class BacklogItem:
    request: PreparedRequest
    enqueued_monotonic: float


@dataclass(frozen=True)
class SenderConfig:
    script_path: Path
    request_report_path: Path
    statistics_report_path: Path
    incident_report_path: Path
    metadata_path: Path
    heartbeat_path: Path | None
    target_host: str
    dispatch_mode: str
    max_inflight: int
    backlog_capacity: int
    backlog_max_age_seconds: float
    request_timeout_seconds: float
    connect_timeout_seconds: float
    progress_log_interval_sec: int
    request_log_flush_interval_sec: int
    response_mode: str
    verify_ssl: bool
    worker_count: int
    worker_index: int | None
    quiet_worker_logs: bool


def _get_int(env_name: str, default: int) -> int:
    raw_value = os.getenv(env_name, str(default))
    try:
        return int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{env_name} must be an integer, got: {raw_value!r}") from exc


def _get_float(env_name: str, default: float) -> float:
    raw_value = os.getenv(env_name, str(default))
    try:
        return float(raw_value)
    except ValueError as exc:
        raise ValueError(f"{env_name} must be a float, got: {raw_value!r}") from exc


def _get_bool(env_name: str, default: bool) -> bool:
    raw_value = os.getenv(env_name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def load_runtime_config() -> SenderConfig:
    target_host = os.getenv("TARGET_HOST", "http://silkeste.fun").rstrip("/")
    if not target_host:
        raise ValueError("TARGET_HOST must not be empty")

    dispatch_mode = os.getenv("SCRIPT_DISPATCH_MODE", "spread").strip().lower()
    if dispatch_mode not in {"spread", "burst"}:
        raise ValueError("SCRIPT_DISPATCH_MODE must be either 'spread' or 'burst'")

    response_mode = os.getenv("REQUEST_RESPONSE_MODE", "release").strip().lower()
    if response_mode not in {"release", "close"}:
        raise ValueError("REQUEST_RESPONSE_MODE must be either 'release' or 'close'")

    progress_log_interval_sec = _get_int("PROGRESS_LOG_INTERVAL_SEC", 60)
    if progress_log_interval_sec < 1:
        raise ValueError("PROGRESS_LOG_INTERVAL_SEC must be at least 1")

    request_log_flush_interval_sec = _get_int("REQUEST_LOG_FLUSH_INTERVAL_SEC", 60)
    if request_log_flush_interval_sec < 1:
        raise ValueError("REQUEST_LOG_FLUSH_INTERVAL_SEC must be at least 1")

    max_inflight = _get_int("MAX_INFLIGHT", 2000)
    if max_inflight < 1:
        raise ValueError("MAX_INFLIGHT must be at least 1")

    backlog_capacity = _get_int("BACKLOG_CAPACITY", 0)
    if backlog_capacity < 0:
        raise ValueError("BACKLOG_CAPACITY must be at least 0")

    backlog_max_age_seconds = _get_float("BACKLOG_MAX_AGE_SECONDS", 1.0)
    if backlog_max_age_seconds <= 0:
        raise ValueError("BACKLOG_MAX_AGE_SECONDS must be greater than 0")

    request_timeout_seconds = _get_float("REQUEST_TIMEOUT_SECONDS", 0.2)
    connect_timeout_seconds = _get_float("CONNECT_TIMEOUT_SECONDS", request_timeout_seconds)
    if request_timeout_seconds <= 0:
        raise ValueError("REQUEST_TIMEOUT_SECONDS must be greater than 0")
    if connect_timeout_seconds <= 0:
        raise ValueError("CONNECT_TIMEOUT_SECONDS must be greater than 0")

    worker_count = _get_int("WORKER_COUNT", 1)
    if worker_count < 1:
        raise ValueError("WORKER_COUNT must be at least 1")

    worker_index = os.getenv("WORKER_INDEX")
    if worker_index is None:
        parsed_worker_index = None
    else:
        parsed_worker_index = int(worker_index)
        if parsed_worker_index < 0 or parsed_worker_index >= worker_count:
            raise ValueError("WORKER_INDEX must be in [0, WORKER_COUNT)")

    return SenderConfig(
        script_path=Path(os.getenv("SCRIPT_CSV_PATH", "/app/scripts/test_script.csv")),
        request_report_path=Path(os.getenv("REQUEST_REPORT_PATH", "/app/output/load_generator_request_report.csv")),
        statistics_report_path=Path(
            os.getenv("STATISTICS_REPORT_PATH", "/app/output/load_generator_statistics_report.csv")
        ),
        incident_report_path=Path(
            os.getenv("INCIDENT_REPORT_PATH", "/app/output/load_generator_incident_report.csv")
        ),
        metadata_path=Path(os.getenv("METADATA_PATH", "/app/output/load_generator_metadata.csv")),
        heartbeat_path=(
            Path(os.environ["HEARTBEAT_PATH"])
            if os.getenv("HEARTBEAT_PATH")
            else None
        ),
        target_host=target_host,
        dispatch_mode=dispatch_mode,
        max_inflight=max_inflight,
        backlog_capacity=backlog_capacity,
        backlog_max_age_seconds=backlog_max_age_seconds,
        request_timeout_seconds=request_timeout_seconds,
        connect_timeout_seconds=connect_timeout_seconds,
        progress_log_interval_sec=progress_log_interval_sec,
        request_log_flush_interval_sec=request_log_flush_interval_sec,
        response_mode=response_mode,
        verify_ssl=_get_bool("REQUEST_SSL_VERIFY", True),
        worker_count=worker_count,
        worker_index=parsed_worker_index,
        quiet_worker_logs=_get_bool("QUIET_WORKER_LOGS", False),
    )


def _parse_timestamp(value: str, line_number: int) -> datetime:
    normalized = value.strip()
    try:
        timestamp = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"Invalid datetime on CSV line {line_number}: {value!r}") from exc

    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError(f"CSV datetime on line {line_number} must include a timezone offset: {value!r}")

    return timestamp.astimezone(timezone.utc)


def _parse_request_count(value: str, line_number: int) -> int:
    try:
        numeric_value = float(value)
    except ValueError as exc:
        raise ValueError(f"Invalid request count on CSV line {line_number}: {value!r}") from exc

    if not numeric_value.is_integer():
        raise ValueError(f"Request count on CSV line {line_number} must be an integer, got {value!r}")

    request_count = int(numeric_value)
    if request_count < 0:
        raise ValueError(f"Request count on CSV line {line_number} must be non-negative, got {value!r}")

    return request_count


def load_script_points(script_path: Path, request_classes: tuple[str, ...]) -> list[ScriptPoint]:
    if not script_path.exists():
        raise FileNotFoundError(f"Script CSV not found: {script_path}")

    required_columns = {"datetime", *(REQUEST_CLASS_COLUMNS[request_class] for request_class in request_classes)}
    points: list[ScriptPoint] = []
    current_time: datetime | None = None
    last_time: datetime | None = None
    zero_request_class_counts = tuple(0 for _ in request_classes)

    with script_path.open(newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        if not reader.fieldnames or not required_columns.issubset(reader.fieldnames):
            raise ValueError(f"CSV must contain columns {sorted(required_columns)}, got {reader.fieldnames}")

        for line_number, row in enumerate(reader, start=2):
            timestamp = _parse_timestamp(row["datetime"], line_number)
            request_class_counts = tuple(
                _parse_request_count(row[REQUEST_CLASS_COLUMNS[request_class]], line_number)
                for request_class in request_classes
            )
            request_count = sum(request_class_counts)

            if last_time is not None and timestamp < last_time:
                raise ValueError(
                    f"CSV timestamps must be sorted ascending after UTC normalization; line {line_number} "
                    f"({timestamp.isoformat()}) is earlier than the previous row ({last_time.isoformat()})"
                )

            if last_time is not None and timestamp == last_time:
                raise ValueError(
                    f"CSV contains duplicate timestamps after UTC normalization on line {line_number}: "
                    f"{timestamp.isoformat()}"
                )

            if current_time is None:
                current_time = timestamp

            while current_time < timestamp:
                points.append(ScriptPoint(current_time, 0, zero_request_class_counts))
                current_time += timedelta(seconds=1)

            points.append(ScriptPoint(timestamp, request_count, request_class_counts))
            current_time = timestamp + timedelta(seconds=1)
            last_time = timestamp

    if not points:
        raise ValueError("No CSV rows found in the script file")

    return points


def _isoformat_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _second_bucket_now() -> str:
    return _isoformat_utc(datetime.now(timezone.utc))


def _parse_second_bucket(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _log_startup_summary(
    config: SenderConfig,
    total_points: int,
    total_planned_requests: int,
    worker_label: str,
) -> None:
    logger.info(
        "Starting custom load generator with %s seconds and %s planned requests from %s using max_inflight=%s "
        "backlog_capacity=%s backlog_max_age=%.3fs dispatch_mode=%s timeout=%.3fs target=%s worker=%s",
        total_points,
        total_planned_requests,
        config.script_path,
        config.max_inflight,
        config.backlog_capacity,
        config.backlog_max_age_seconds,
        config.dispatch_mode,
        config.request_timeout_seconds,
        config.target_host,
        worker_label,
    )


class RequestReportWriter:
    def __init__(self, output_path: Path):
        self.output_path = output_path
        self.counts: dict[tuple[str, str], int] = defaultdict(int)
        self.flushed_keys: set[tuple[str, str]] = set()

    def reset(self) -> None:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        with self.output_path.open("w", newline="", encoding="utf-8") as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(["second", "url", "count"])
        self.counts.clear()
        self.flushed_keys.clear()

    def record(self, second_bucket: str, report_url: str) -> None:
        self.counts[(second_bucket, report_url)] += 1

    def flush_closed(self, final: bool = False) -> None:
        current_second = _second_bucket_now()
        rows = []
        for key, count in sorted(self.counts.items()):
            second_bucket, report_url = key
            if key in self.flushed_keys:
                continue
            if not final and second_bucket >= current_second:
                continue
            rows.append((second_bucket, report_url, count))
            self.flushed_keys.add(key)

        if not rows:
            return

        with self.output_path.open("a", newline="", encoding="utf-8") as csv_file:
            writer = csv.writer(csv_file)
            for second_bucket, report_url, count in rows:
                writer.writerow([second_bucket, report_url, count])


class StatisticsReportWriter:
    COLUMN_NAMES = (
        "planned",
        "scheduled",
        "enqueued",
        "started",
        "started_immediate",
        "started_from_backlog",
        "completed",
        "failed",
        "timed_out",
        "dropped_capacity",
        "dropped_backlog_full",
        "backlog_expired",
    )

    def __init__(self, output_path: Path):
        self.output_path = output_path
        self.counts: dict[str, dict[str, int]] = defaultdict(lambda: {name: 0 for name in self.COLUMN_NAMES})
        self.first_second: datetime | None = None
        self.last_flushed_second: datetime | None = None
        self.latest_seen_second: datetime | None = None

    def reset(self, first_second: datetime) -> None:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        with self.output_path.open("w", newline="", encoding="utf-8") as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(["second", *self.COLUMN_NAMES])

        normalized_first_second = first_second.replace(microsecond=0)
        self.counts.clear()
        self.first_second = normalized_first_second
        self.last_flushed_second = normalized_first_second - timedelta(seconds=1)
        self.latest_seen_second = None

    def record(self, second_bucket: str, column_name: str, count: int = 1) -> None:
        if column_name not in self.COLUMN_NAMES:
            raise ValueError(f"Unknown statistics column: {column_name}")

        self.counts[second_bucket][column_name] += count
        bucket_time = _parse_second_bucket(second_bucket)
        if self.latest_seen_second is None or bucket_time > self.latest_seen_second:
            self.latest_seen_second = bucket_time

    def flush_closed(self, final: bool = False) -> None:
        if self.first_second is None or self.last_flushed_second is None:
            return

        if final:
            closed_through = self.latest_seen_second
            if closed_through is None:
                return
        else:
            closed_through = _parse_second_bucket(_second_bucket_now()) - timedelta(seconds=1)
            if closed_through < self.first_second:
                return

        if closed_through <= self.last_flushed_second:
            return

        rows = []
        current = self.last_flushed_second + timedelta(seconds=1)
        while current <= closed_through:
            second_bucket = _isoformat_utc(current)
            row = self.counts.pop(second_bucket, None)
            if row is None:
                row = {name: 0 for name in self.COLUMN_NAMES}
            rows.append([second_bucket, *(row[name] for name in self.COLUMN_NAMES)])
            current += timedelta(seconds=1)

        with self.output_path.open("a", newline="", encoding="utf-8") as csv_file:
            writer = csv.writer(csv_file)
            writer.writerows(rows)

        self.last_flushed_second = closed_through


class IncidentReportWriter:
    def __init__(self, output_path: Path):
        self.output_path = output_path
        self.rows: list[tuple[str, str, str, str, str]] = []
        self._flushed_count = 0

    def reset(self) -> None:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        with self.output_path.open("w", newline="", encoding="utf-8") as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(["timestamp", "second", "url", "incident_type", "message"])
        self.rows.clear()
        self._flushed_count = 0

    def record(self, timestamp: str, second_bucket: str, url: str, incident_type: str, message: str) -> None:
        self.rows.append((timestamp, second_bucket, url, incident_type, message))

    def flush(self) -> None:
        if self._flushed_count >= len(self.rows):
            return

        with self.output_path.open("a", newline="", encoding="utf-8") as csv_file:
            writer = csv.writer(csv_file)
            for row in self.rows[self._flushed_count :]:
                writer.writerow(row)

        self._flushed_count = len(self.rows)


class LoadSender:
    def __init__(self, config: SenderConfig):
        self.config = config
        self.workload_config = load_workload_config()
        self.workload_planner = WorkloadPlanner(self.workload_config)
        self.timeline = load_script_points(config.script_path, self.workload_config.request_classes)
        self.report_writer = RequestReportWriter(config.request_report_path)
        self.statistics_writer = StatisticsReportWriter(config.statistics_report_path)
        self.incident_writer = IncidentReportWriter(config.incident_report_path)
        self.token_queue: asyncio.Queue[object] = asyncio.Queue(maxsize=config.max_inflight)
        for _ in range(config.max_inflight):
            self.token_queue.put_nowait(object())
        self.backlog_queue: deque[BacklogItem] = deque()
        self.backlog_available = asyncio.Event()

        self.inflight_tasks: set[asyncio.Task[None]] = set()
        self.stop_requested = asyncio.Event()
        self.second_request_offsets = self._build_second_request_offsets()

        self.total_points = len(self.timeline)
        self.total_planned_requests = sum(point.requests for point in self.timeline)
        self.started_requests = 0
        self.completed_requests = 0
        self.failed_requests = 0
        self.timed_out_requests = 0
        self.dropped_due_to_capacity = 0
        self.dropped_backlog_full_requests = 0
        self.backlog_expired_requests = 0
        self.enqueued_requests = 0
        self.started_immediate_requests = 0
        self.started_from_backlog_requests = 0
        self.planned_requests_so_far = 0
        self.scheduled_requests = 0
        self.dispatched_seconds = 0
        self.backlog_max_depth = 0
        self.scheduling_complete = False

        self.run_started_at: datetime | None = None
        self._progress_task: asyncio.Task[None] | None = None
        self._backlog_task: asyncio.Task[None] | None = None
        self._last_flush_monotonic = 0.0
        self._previous_loop_exception_handler = None

    def _heartbeat_payload(self) -> dict[str, int | bool]:
        return {
            "total_points": self.total_points,
            "total_planned_requests": self.total_planned_requests,
            "dispatched_seconds": self.dispatched_seconds,
            "planned_requests_so_far": self.planned_requests_so_far,
            "scheduled_requests": self.scheduled_requests,
            "enqueued_requests": self.enqueued_requests,
            "started_requests": self.started_requests,
            "started_immediate_requests": self.started_immediate_requests,
            "started_from_backlog_requests": self.started_from_backlog_requests,
            "completed_requests": self.completed_requests,
            "failed_requests": self.failed_requests,
            "timed_out_requests": self.timed_out_requests,
            "dropped_due_to_capacity": self.dropped_due_to_capacity,
            "dropped_backlog_full_requests": self.dropped_backlog_full_requests,
            "backlog_expired_requests": self.backlog_expired_requests,
            "inflight_count": self.inflight_count,
            "backlog_depth": len(self.backlog_queue),
            "backlog_max_depth": self.backlog_max_depth,
            "done": self.scheduling_complete and not self.inflight_tasks and not self.backlog_queue,
        }

    def _write_heartbeat(self) -> None:
        if self.config.heartbeat_path is None:
            return

        self.config.heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
        payload = self._heartbeat_payload()
        temp_path = self.config.heartbeat_path.with_suffix(f"{self.config.heartbeat_path.suffix}.tmp")
        with temp_path.open("w", encoding="utf-8") as heartbeat_file:
            json.dump(payload, heartbeat_file, separators=(",", ":"))
        temp_path.replace(self.config.heartbeat_path)

    def _build_second_request_offsets(self) -> list[int]:
        offsets: list[int] = []
        running_total = 0
        for point in self.timeline:
            offsets.append(running_total)
            running_total += point.requests
        return offsets

    async def run(self) -> None:
        import aiohttp

        self.report_writer.reset()
        self.incident_writer.reset()
        self.run_started_at = datetime.now(timezone.utc)
        self.statistics_writer.reset(self.run_started_at)
        if self.config.worker_index is None:
            self._write_metadata()
        self._install_signal_handlers()

        _log_startup_summary(
            self.config,
            self.total_points,
            self.total_planned_requests,
            f"{0 if self.config.worker_index is None else self.config.worker_index}/{self.config.worker_count}",
        )
        logger.info("Workload request classes enabled: %s", ", ".join(self.workload_planner.operation_names()))

        connector = aiohttp.TCPConnector(
            limit=self.config.max_inflight,
            limit_per_host=self.config.max_inflight,
            ssl=self.config.verify_ssl,
            ttl_dns_cache=300,
            enable_cleanup_closed=True,
        )
        timeout = aiohttp.ClientTimeout(
            total=self.config.request_timeout_seconds,
            connect=self.config.connect_timeout_seconds,
            sock_connect=self.config.connect_timeout_seconds,
            sock_read=self.config.request_timeout_seconds,
        )

        async with aiohttp.ClientSession(
            base_url=self.config.target_host,
            connector=connector,
            timeout=timeout,
            trust_env=False,
        ) as session:
            self._backlog_task = asyncio.create_task(self._backlog_loop(session))
            loop = asyncio.get_running_loop()
            self._install_loop_exception_handler(loop)
            self._progress_task = asyncio.create_task(self._progress_loop())
            start_monotonic = loop.time()

            try:
                for second_index, point in enumerate(self.timeline):
                    if self.stop_requested.is_set():
                        break

                    target_offset = float(second_index)
                    remaining = (start_monotonic + target_offset) - loop.time()
                    if remaining > 0:
                        await asyncio.sleep(remaining)

                    await self._dispatch_second(session, second_index, point, start_monotonic)
                    self.dispatched_seconds = second_index + 1
            finally:
                self.scheduling_complete = True
                self.backlog_available.set()
                if self._progress_task is not None:
                    self._progress_task.cancel()
                    await asyncio.gather(self._progress_task, return_exceptions=True)
                self._restore_loop_exception_handler(loop)

            if self._backlog_task is not None:
                await asyncio.gather(self._backlog_task, return_exceptions=True)

            if self.inflight_tasks:
                await asyncio.gather(*self.inflight_tasks, return_exceptions=True)

        self.report_writer.flush_closed(final=True)
        self.statistics_writer.flush_closed(final=True)
        self.incident_writer.flush()
        self._write_heartbeat()
        logger.info(
            "Run complete: total_planned=%s planned_so_far=%s scheduled=%s enqueued=%s started=%s started_immediate=%s "
            "started_from_backlog=%s completed=%s failed=%s timed_out=%s dropped_capacity=%s dropped_backlog_full=%s "
            "backlog_expired=%s inflight=%s backlog_depth=%s backlog_max_depth=%s",
            self.total_planned_requests,
            self.planned_requests_so_far,
            self.scheduled_requests,
            self.enqueued_requests,
            self.started_requests,
            self.started_immediate_requests,
            self.started_from_backlog_requests,
            self.completed_requests,
            self.failed_requests,
            self.timed_out_requests,
            self.dropped_due_to_capacity,
            self.dropped_backlog_full_requests,
            self.backlog_expired_requests,
            self.inflight_count,
            len(self.backlog_queue),
            self.backlog_max_depth,
        )

    @property
    def inflight_count(self) -> int:
        return self.config.max_inflight - self.token_queue.qsize()

    def _wall_clock_bucket_for_script_second(self, second_index: int) -> str:
        if self.run_started_at is None:
            return _second_bucket_now()
        run_start_second = self.run_started_at.replace(microsecond=0)
        return _isoformat_utc(run_start_second + timedelta(seconds=second_index))

    async def _dispatch_second(
        self,
        session: "aiohttp.ClientSession",
        second_index: int,
        point: ScriptPoint,
        start_monotonic: float,
    ) -> None:
        request_count = point.requests
        planned_second_bucket = self._wall_clock_bucket_for_script_second(second_index)
        second_base_offset = self.second_request_offsets[second_index]
        assigned_request_count = sum(
            1
            for request_index in range(request_count)
            if self._should_handle_request(second_base_offset + request_index)
        )
        self.statistics_writer.record(planned_second_bucket, "planned", assigned_request_count)
        self.planned_requests_so_far += assigned_request_count
        if request_count <= 0:
            return

        if self.config.dispatch_mode == "burst" or request_count == 1:
            for request_index in range(request_count):
                global_request_index = second_base_offset + request_index
                if not self._should_handle_request(global_request_index):
                    continue
                self._launch_or_backlog(session, second_index, request_index, global_request_index)
        else:
            loop = asyncio.get_running_loop()
            second_start = start_monotonic + float(second_index)
            for request_index in range(request_count):
                scheduled_at = second_start + (request_index / request_count)
                remaining = scheduled_at - loop.time()
                if remaining > 0:
                    await asyncio.sleep(remaining)
                global_request_index = second_base_offset + request_index
                if not self._should_handle_request(global_request_index):
                    continue
                self._launch_or_backlog(session, second_index, request_index, global_request_index)

        self._flush_request_report_if_due()

    def _should_handle_request(self, global_request_index: int) -> bool:
        if self.config.worker_index is None:
            return True
        return (global_request_index % self.config.worker_count) == self.config.worker_index

    def _launch_or_backlog(
        self,
        session: "aiohttp.ClientSession",
        second_index: int,
        request_index: int,
        global_request_index: int,
    ) -> None:
        second_bucket = _second_bucket_now()
        self.scheduled_requests += 1
        self.statistics_writer.record(second_bucket, "scheduled")

        request_class = self.workload_planner.request_class_for_index(
            self.timeline[second_index].request_class_counts,
            request_index,
        )
        request = self.workload_planner.build_request(request_class)

        try:
            token = self.token_queue.get_nowait()
        except asyncio.QueueEmpty:
            self._enqueue_or_drop(second_bucket, request)
            return

        self._start_request_task(session, token, request, second_bucket, from_backlog=False)

    def _enqueue_or_drop(self, second_bucket: str, request: PreparedRequest) -> None:
        if self.config.backlog_capacity > 0 and len(self.backlog_queue) < self.config.backlog_capacity:
            item = BacklogItem(request=request, enqueued_monotonic=asyncio.get_running_loop().time())
            self.backlog_queue.append(item)
            self.enqueued_requests += 1
            self.statistics_writer.record(second_bucket, "enqueued")
            self.backlog_max_depth = max(self.backlog_max_depth, len(self.backlog_queue))
            self.backlog_available.set()
            return

        self.dropped_due_to_capacity += 1
        self.statistics_writer.record(second_bucket, "dropped_capacity")
        if self.config.backlog_capacity > 0:
            self.dropped_backlog_full_requests += 1
            self.statistics_writer.record(second_bucket, "dropped_backlog_full")

    def _start_request_task(
        self,
        session: "aiohttp.ClientSession",
        token: object,
        request: PreparedRequest,
        second_bucket: str,
        from_backlog: bool,
    ) -> None:
        self.started_requests += 1
        self.report_writer.record(second_bucket, request.report_url)
        self.statistics_writer.record(second_bucket, "started")
        if from_backlog:
            self.started_from_backlog_requests += 1
            self.statistics_writer.record(second_bucket, "started_from_backlog")
        else:
            self.started_immediate_requests += 1
            self.statistics_writer.record(second_bucket, "started_immediate")

        task = asyncio.create_task(self._execute_request(session, token, request))
        self.inflight_tasks.add(task)
        task.add_done_callback(self.inflight_tasks.discard)

    async def _backlog_loop(self, session: "aiohttp.ClientSession") -> None:
        while True:
            if not self.backlog_queue:
                if self.scheduling_complete:
                    return
                self.backlog_available.clear()
                try:
                    await asyncio.wait_for(self.backlog_available.wait(), timeout=0.5)
                except TimeoutError:
                    pass
                continue

            head_item = self.backlog_queue[0]
            if self._is_backlog_item_expired(head_item):
                self.backlog_queue.popleft()
                self.dropped_due_to_capacity += 1
                self.backlog_expired_requests += 1
                second_bucket = _second_bucket_now()
                self.statistics_writer.record(second_bucket, "dropped_capacity")
                self.statistics_writer.record(second_bucket, "backlog_expired")
                continue

            token = await self.token_queue.get()
            if not self.backlog_queue:
                self.token_queue.put_nowait(token)
                continue

            item = self.backlog_queue.popleft()
            if self._is_backlog_item_expired(item):
                self.token_queue.put_nowait(token)
                self.dropped_due_to_capacity += 1
                self.backlog_expired_requests += 1
                second_bucket = _second_bucket_now()
                self.statistics_writer.record(second_bucket, "dropped_capacity")
                self.statistics_writer.record(second_bucket, "backlog_expired")
                continue

            self._start_request_task(
                session=session,
                token=token,
                request=item.request,
                second_bucket=_second_bucket_now(),
                from_backlog=True,
            )

    def _is_backlog_item_expired(self, item: BacklogItem) -> bool:
        return (asyncio.get_running_loop().time() - item.enqueued_monotonic) > self.config.backlog_max_age_seconds

    async def _execute_request(
        self,
        session: "aiohttp.ClientSession",
        token: object,
        request: PreparedRequest,
    ) -> None:
        import aiohttp

        try:
            async with asyncio.timeout(self.config.request_timeout_seconds):
                async with session.request(request.method, request.path, json=request.json_body) as response:
                    if self.config.response_mode == "close":
                        response.close()
                    else:
                        response.release()

                    if response.status >= 400:
                        self.failed_requests += 1
                        self.statistics_writer.record(_second_bucket_now(), "failed")
                    else:
                        self.completed_requests += 1
                        self.statistics_writer.record(_second_bucket_now(), "completed")
        except TimeoutError:
            self.timed_out_requests += 1
            self.statistics_writer.record(_second_bucket_now(), "timed_out")
        except aiohttp.ClientError:
            self.failed_requests += 1
            self.statistics_writer.record(_second_bucket_now(), "failed")
            self._record_incident_if_relevant(request, "client_error", sys.exc_info()[1])
        except Exception:
            logger.exception("Unhandled request failure for %s %s", request.method, request.path)
            self.failed_requests += 1
            self.statistics_writer.record(_second_bucket_now(), "failed")
            self._record_incident_if_relevant(request, "unexpected_error", sys.exc_info()[1])
        finally:
            self.token_queue.put_nowait(token)

    async def _progress_loop(self) -> None:
        while not self.stop_requested.is_set():
            await asyncio.sleep(self.config.progress_log_interval_sec)
            self.report_writer.flush_closed()
            self.statistics_writer.flush_closed()
            self.incident_writer.flush()
            self._write_heartbeat()
            percentage = (self.dispatched_seconds / max(self.total_points, 1)) * 100
            if not self.config.quiet_worker_logs:
                logger.info(
                    "Progress %.1f%% (%s/%s seconds) total_planned=%s planned_so_far=%s scheduled=%s enqueued=%s started=%s "
                    "started_immediate=%s started_from_backlog=%s completed=%s failed=%s timed_out=%s dropped_capacity=%s "
                    "dropped_backlog_full=%s backlog_expired=%s inflight=%s backlog_depth=%s backlog_max_depth=%s",
                    percentage,
                    self.dispatched_seconds,
                    self.total_points,
                    self.total_planned_requests,
                    self.planned_requests_so_far,
                    self.scheduled_requests,
                    self.enqueued_requests,
                    self.started_requests,
                    self.started_immediate_requests,
                    self.started_from_backlog_requests,
                    self.completed_requests,
                    self.failed_requests,
                    self.timed_out_requests,
                    self.dropped_due_to_capacity,
                    self.dropped_backlog_full_requests,
                    self.backlog_expired_requests,
                    self.inflight_count,
                    len(self.backlog_queue),
                    self.backlog_max_depth,
                )

    def _flush_request_report_if_due(self) -> None:
        now = asyncio.get_running_loop().time()
        if (now - self._last_flush_monotonic) < self.config.request_log_flush_interval_sec:
            return

        self.report_writer.flush_closed()
        self.statistics_writer.flush_closed()
        self.incident_writer.flush()
        self._last_flush_monotonic = now

    def _record_incident_if_relevant(self, request: PreparedRequest, incident_type: str, exc: BaseException | None) -> None:
        if exc is None:
            return

        message = str(exc)
        if "Connection reset by peer" not in message:
            return

        timestamp = datetime.now(timezone.utc).isoformat()
        second_bucket = _second_bucket_now()
        self.incident_writer.record(
            timestamp=timestamp,
            second_bucket=second_bucket,
            url=request.report_url,
            incident_type=incident_type,
            message=message,
        )

    def _record_loop_incident_if_relevant(self, context: dict[str, object]) -> None:
        exc = context.get("exception")
        message = context.get("message")
        combined_message = " | ".join(
            part for part in [str(exc) if exc is not None else "", str(message) if message is not None else ""] if part
        )
        if "Connection reset by peer" not in combined_message:
            return

        timestamp = datetime.now(timezone.utc).isoformat()
        second_bucket = _second_bucket_now()
        self.incident_writer.record(
            timestamp=timestamp,
            second_bucket=second_bucket,
            url="__event_loop__",
            incident_type="loop_exception",
            message=combined_message,
        )

    def _install_loop_exception_handler(self, loop: asyncio.AbstractEventLoop) -> None:
        self._previous_loop_exception_handler = loop.get_exception_handler()

        def _handle_exception(event_loop: asyncio.AbstractEventLoop, context: dict[str, object]) -> None:
            self._record_loop_incident_if_relevant(context)
            if self._previous_loop_exception_handler is not None:
                self._previous_loop_exception_handler(event_loop, context)
            else:
                event_loop.default_exception_handler(context)

        loop.set_exception_handler(_handle_exception)

    def _restore_loop_exception_handler(self, loop: asyncio.AbstractEventLoop) -> None:
        loop.set_exception_handler(self._previous_loop_exception_handler)
        self._previous_loop_exception_handler = None

    def _write_metadata(self) -> None:
        if self.run_started_at is None:
            return

        self.config.metadata_path.parent.mkdir(parents=True, exist_ok=True)
        run_start_second = self.run_started_at.replace(microsecond=0)
        with self.config.metadata_path.open("w", newline="", encoding="utf-8") as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(
                [
                    "run_start_time",
                    "run_start_second",
                    "script_path",
                    "script_start_time",
                    "script_end_time",
                    "script_seconds",
                    "planned_requests",
                ]
            )
            writer.writerow(
                [
                    self.run_started_at.isoformat(),
                    run_start_second.isoformat(),
                    str(self.config.script_path),
                    self.timeline[0].timestamp.isoformat(),
                    self.timeline[-1].timestamp.isoformat(),
                    self.total_points,
                    self.total_planned_requests,
                ]
            )

    def _install_signal_handlers(self) -> None:
        loop = asyncio.get_running_loop()

        def _request_stop() -> None:
            logger.warning("Stop signal received, no new requests will be scheduled.")
            self.stop_requested.set()

        for signame in ("SIGINT", "SIGTERM"):
            sig = getattr(signal, signame, None)
            if sig is None:
                continue
            try:
                loop.add_signal_handler(sig, _request_stop)
            except NotImplementedError:
                signal.signal(sig, lambda *_args: _request_stop())


def configure_logging() -> None:
    log_level = os.getenv("LOG_LEVEL", "INFO").strip().upper()
    if _get_bool("QUIET_WORKER_LOGS", False):
        log_level = "WARNING"
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )


async def async_main() -> int:
    config = load_runtime_config()
    sender = LoadSender(config)
    await sender.run()
    return 0


def _write_metadata(
    metadata_path: Path,
    script_path: Path,
    timeline: list[ScriptPoint],
    run_started_at: datetime,
) -> None:
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    run_start_second = run_started_at.replace(microsecond=0)
    with metadata_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(
            [
                "run_start_time",
                "run_start_second",
                "script_path",
                "script_start_time",
                "script_end_time",
                "script_seconds",
                "planned_requests",
            ]
        )
        writer.writerow(
            [
                run_started_at.isoformat(),
                run_start_second.isoformat(),
                str(script_path),
                timeline[0].timestamp.isoformat(),
                timeline[-1].timestamp.isoformat(),
                len(timeline),
                sum(point.requests for point in timeline),
            ]
        )


def _worker_output_path(base_path: Path, worker_index: int) -> Path:
    return base_path.with_name(f"{base_path.stem}.worker{worker_index}{base_path.suffix}")


def _read_heartbeat(path: Path) -> dict[str, int | bool] | None:
    if not path.exists():
        return None

    try:
        with path.open(encoding="utf-8") as heartbeat_file:
            return json.load(heartbeat_file)
    except (OSError, json.JSONDecodeError):
        return None


def _log_aggregated_worker_progress(heartbeat_paths: list[Path]) -> None:
    heartbeats = [heartbeat for path in heartbeat_paths if (heartbeat := _read_heartbeat(path)) is not None]
    if not heartbeats:
        return

    total_points = max(int(heartbeat["total_points"]) for heartbeat in heartbeats)
    dispatched_seconds = max(int(heartbeat["dispatched_seconds"]) for heartbeat in heartbeats)
    total_planned_requests = max(int(heartbeat["total_planned_requests"]) for heartbeat in heartbeats)
    planned_requests_so_far = sum(int(heartbeat["planned_requests_so_far"]) for heartbeat in heartbeats)
    scheduled_requests = sum(int(heartbeat["scheduled_requests"]) for heartbeat in heartbeats)
    enqueued_requests = sum(int(heartbeat["enqueued_requests"]) for heartbeat in heartbeats)
    started_requests = sum(int(heartbeat["started_requests"]) for heartbeat in heartbeats)
    started_immediate_requests = sum(int(heartbeat["started_immediate_requests"]) for heartbeat in heartbeats)
    started_from_backlog_requests = sum(int(heartbeat["started_from_backlog_requests"]) for heartbeat in heartbeats)
    completed_requests = sum(int(heartbeat["completed_requests"]) for heartbeat in heartbeats)
    failed_requests = sum(int(heartbeat["failed_requests"]) for heartbeat in heartbeats)
    timed_out_requests = sum(int(heartbeat["timed_out_requests"]) for heartbeat in heartbeats)
    dropped_due_to_capacity = sum(int(heartbeat["dropped_due_to_capacity"]) for heartbeat in heartbeats)
    dropped_backlog_full_requests = sum(int(heartbeat["dropped_backlog_full_requests"]) for heartbeat in heartbeats)
    backlog_expired_requests = sum(int(heartbeat["backlog_expired_requests"]) for heartbeat in heartbeats)
    inflight_count = sum(int(heartbeat["inflight_count"]) for heartbeat in heartbeats)
    backlog_depth = sum(int(heartbeat["backlog_depth"]) for heartbeat in heartbeats)
    backlog_max_depth = sum(int(heartbeat["backlog_max_depth"]) for heartbeat in heartbeats)

    percentage = (dispatched_seconds / max(total_points, 1)) * 100
    logger.info(
        "Progress %.1f%% (%s/%s seconds) total_planned=%s planned_so_far=%s scheduled=%s enqueued=%s started=%s "
        "started_immediate=%s started_from_backlog=%s completed=%s failed=%s timed_out=%s dropped_capacity=%s "
        "dropped_backlog_full=%s backlog_expired=%s inflight=%s backlog_depth=%s backlog_max_depth=%s",
        percentage,
        dispatched_seconds,
        total_points,
        total_planned_requests,
        planned_requests_so_far,
        scheduled_requests,
        enqueued_requests,
        started_requests,
        started_immediate_requests,
        started_from_backlog_requests,
        completed_requests,
        failed_requests,
        timed_out_requests,
        dropped_due_to_capacity,
        dropped_backlog_full_requests,
        backlog_expired_requests,
        inflight_count,
        backlog_depth,
        backlog_max_depth,
    )


def _merge_request_reports(input_paths: list[Path], output_path: Path) -> None:
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for input_path in input_paths:
        if not input_path.exists():
            continue
        with input_path.open(newline="", encoding="utf-8") as csv_file:
            reader = csv.DictReader(csv_file)
            for row in reader:
                counts[(row["second"], row["url"])] += int(row["count"])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(["second", "url", "count"])
        for (second, url), count in sorted(counts.items()):
            writer.writerow([second, url, count])


def _merge_statistics_reports(input_paths: list[Path], output_path: Path) -> None:
    totals: dict[str, dict[str, int]] = defaultdict(lambda: {name: 0 for name in StatisticsReportWriter.COLUMN_NAMES})
    for input_path in input_paths:
        if not input_path.exists():
            continue
        with input_path.open(newline="", encoding="utf-8") as csv_file:
            reader = csv.DictReader(csv_file)
            for row in reader:
                second = row["second"]
                for column_name in StatisticsReportWriter.COLUMN_NAMES:
                    totals[second][column_name] += int(row[column_name])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(["second", *StatisticsReportWriter.COLUMN_NAMES])
        for second in sorted(totals):
            writer.writerow([second, *(totals[second][column_name] for column_name in StatisticsReportWriter.COLUMN_NAMES)])


def _merge_incident_reports(input_paths: list[Path], output_path: Path) -> None:
    rows: list[tuple[str, str, str, str, str]] = []
    for input_path in input_paths:
        if not input_path.exists():
            continue
        with input_path.open(newline="", encoding="utf-8") as csv_file:
            reader = csv.DictReader(csv_file)
            for row in reader:
                rows.append((row["timestamp"], row["second"], row["url"], row["incident_type"], row["message"]))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(["timestamp", "second", "url", "incident_type", "message"])
        for row in sorted(rows):
            writer.writerow(row)


def _merge_worker_outputs_live(
    request_paths: list[Path],
    statistics_paths: list[Path],
    incident_paths: list[Path],
    request_output_path: Path,
    statistics_output_path: Path,
    incident_output_path: Path,
) -> None:
    _merge_request_reports(request_paths, request_output_path)
    _merge_statistics_reports(statistics_paths, statistics_output_path)
    _merge_incident_reports(incident_paths, incident_output_path)


def _run_multi_worker() -> int:
    config = load_runtime_config()
    workload_config = load_workload_config()
    timeline = load_script_points(config.script_path, workload_config.request_classes)
    run_started_at = datetime.now(timezone.utc)
    _write_metadata(config.metadata_path, config.script_path, timeline, run_started_at)
    _log_startup_summary(
        config,
        len(timeline),
        sum(point.requests for point in timeline),
        f"parent/{config.worker_count}",
    )

    worker_processes: list[subprocess.Popen] = []
    request_paths: list[Path] = []
    statistics_paths: list[Path] = []
    incident_paths: list[Path] = []
    heartbeat_paths: list[Path] = []

    for worker_index in range(config.worker_count):
        worker_request_path = _worker_output_path(config.request_report_path, worker_index)
        worker_statistics_path = _worker_output_path(config.statistics_report_path, worker_index)
        worker_incident_path = _worker_output_path(config.incident_report_path, worker_index)
        worker_heartbeat_path = _worker_output_path(
            config.statistics_report_path.with_name("load_generator_worker_heartbeat.json"),
            worker_index,
        )

        request_paths.append(worker_request_path)
        statistics_paths.append(worker_statistics_path)
        incident_paths.append(worker_incident_path)
        heartbeat_paths.append(worker_heartbeat_path)

        env = os.environ.copy()
        env["WORKER_INDEX"] = str(worker_index)
        env["WORKER_COUNT"] = str(config.worker_count)
        env["REQUEST_REPORT_PATH"] = str(worker_request_path)
        env["STATISTICS_REPORT_PATH"] = str(worker_statistics_path)
        env["INCIDENT_REPORT_PATH"] = str(worker_incident_path)
        env["METADATA_PATH"] = str(config.metadata_path)
        env["HEARTBEAT_PATH"] = str(worker_heartbeat_path)
        env["QUIET_WORKER_LOGS"] = "true"

        worker_processes.append(
            subprocess.Popen(
                [sys.executable, "-u", str(Path(__file__).resolve())],
                env=env,
            )
        )

    while True:
        if all(process.poll() is not None for process in worker_processes):
            break
        time.sleep(config.progress_log_interval_sec)
        _merge_worker_outputs_live(
            request_paths=request_paths,
            statistics_paths=statistics_paths,
            incident_paths=incident_paths,
            request_output_path=config.request_report_path,
            statistics_output_path=config.statistics_report_path,
            incident_output_path=config.incident_report_path,
        )
        _log_aggregated_worker_progress(heartbeat_paths)

    _merge_worker_outputs_live(
        request_paths=request_paths,
        statistics_paths=statistics_paths,
        incident_paths=incident_paths,
        request_output_path=config.request_report_path,
        statistics_output_path=config.statistics_report_path,
        incident_output_path=config.incident_report_path,
    )
    _log_aggregated_worker_progress(heartbeat_paths)
    exit_codes = [process.wait() for process in worker_processes]

    for path in [*request_paths, *statistics_paths, *incident_paths, *heartbeat_paths]:
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    if any(code != 0 for code in exit_codes):
        logger.error("One or more worker processes failed: exit_codes=%s", exit_codes)
        return 1
    logger.info("Merged %s worker reports into %s", config.worker_count, config.request_report_path.parent)
    return 0


def main() -> int:
    configure_logging()
    try:
        config = load_runtime_config()
        if config.worker_count > 1 and config.worker_index is None:
            logger.info("Launching %s worker processes for sharded generator test", config.worker_count)
            return _run_multi_worker()
        return asyncio.run(async_main())
    except KeyboardInterrupt:
        logger.warning("Interrupted by user.")
        return 130
    except Exception:
        logger.exception("Custom load generator failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
