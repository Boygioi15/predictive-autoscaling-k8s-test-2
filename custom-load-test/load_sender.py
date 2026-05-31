from __future__ import annotations

import asyncio
import csv
import logging
import os
import signal
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import aiohttp

from workload import PreparedRequest, WorkloadPlanner, load_workload_config

logger = logging.getLogger("custom_load_test")


@dataclass(frozen=True)
class ScriptPoint:
    timestamp: datetime
    requests: int


@dataclass(frozen=True)
class SenderConfig:
    script_path: Path
    request_report_path: Path
    statistics_report_path: Path
    metadata_path: Path
    target_host: str
    dispatch_mode: str
    max_inflight: int
    request_timeout_seconds: float
    connect_timeout_seconds: float
    progress_log_interval_sec: int
    request_log_flush_interval_sec: int
    response_mode: str
    verify_ssl: bool


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

    request_timeout_seconds = _get_float("REQUEST_TIMEOUT_SECONDS", 0.2)
    connect_timeout_seconds = _get_float("CONNECT_TIMEOUT_SECONDS", request_timeout_seconds)
    if request_timeout_seconds <= 0:
        raise ValueError("REQUEST_TIMEOUT_SECONDS must be greater than 0")
    if connect_timeout_seconds <= 0:
        raise ValueError("CONNECT_TIMEOUT_SECONDS must be greater than 0")

    return SenderConfig(
        script_path=Path(os.getenv("SCRIPT_CSV_PATH", "/mnt/shares/test_script.csv")),
        request_report_path=Path(os.getenv("REQUEST_REPORT_PATH", "/mnt/shares/load_test_request_report.csv")),
        statistics_report_path=Path(
            os.getenv("STATISTICS_REPORT_PATH", "/mnt/shares/load_test_statistics_report.csv")
        ),
        metadata_path=Path(os.getenv("METADATA_PATH", "/mnt/shares/load_test_metadata.csv")),
        target_host=target_host,
        dispatch_mode=dispatch_mode,
        max_inflight=max_inflight,
        request_timeout_seconds=request_timeout_seconds,
        connect_timeout_seconds=connect_timeout_seconds,
        progress_log_interval_sec=progress_log_interval_sec,
        request_log_flush_interval_sec=request_log_flush_interval_sec,
        response_mode=response_mode,
        verify_ssl=_get_bool("REQUEST_SSL_VERIFY", True),
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


def load_script_points(script_path: Path) -> list[ScriptPoint]:
    if not script_path.exists():
        raise FileNotFoundError(f"Script CSV not found: {script_path}")

    required_columns = {"datetime", "requests"}
    points: list[ScriptPoint] = []
    current_time: datetime | None = None
    last_time: datetime | None = None

    with script_path.open(newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        if not reader.fieldnames or not required_columns.issubset(reader.fieldnames):
            raise ValueError(f"CSV must contain columns {sorted(required_columns)}, got {reader.fieldnames}")

        for line_number, row in enumerate(reader, start=2):
            timestamp = _parse_timestamp(row["datetime"], line_number)
            request_count = _parse_request_count(row["requests"], line_number)

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
                points.append(ScriptPoint(current_time, 0))
                current_time += timedelta(seconds=1)

            points.append(ScriptPoint(timestamp, request_count))
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
        "started",
        "completed",
        "failed",
        "timed_out",
        "dropped_capacity",
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


class LoadSender:
    def __init__(self, config: SenderConfig):
        self.config = config
        self.timeline = load_script_points(config.script_path)
        self.workload_planner = WorkloadPlanner(load_workload_config())
        self.report_writer = RequestReportWriter(config.request_report_path)
        self.statistics_writer = StatisticsReportWriter(config.statistics_report_path)
        self.token_queue: asyncio.Queue[object] = asyncio.Queue(maxsize=config.max_inflight)
        for _ in range(config.max_inflight):
            self.token_queue.put_nowait(object())

        self.inflight_tasks: set[asyncio.Task[None]] = set()
        self.stop_requested = asyncio.Event()

        self.total_points = len(self.timeline)
        self.total_planned_requests = sum(point.requests for point in self.timeline)
        self.started_requests = 0
        self.completed_requests = 0
        self.failed_requests = 0
        self.timed_out_requests = 0
        self.dropped_due_to_capacity = 0
        self.planned_requests_so_far = 0
        self.scheduled_requests = 0
        self.dispatched_seconds = 0

        self.run_started_at: datetime | None = None
        self._progress_task: asyncio.Task[None] | None = None
        self._last_flush_monotonic = 0.0

    async def run(self) -> None:
        import aiohttp

        self.report_writer.reset()
        self.run_started_at = datetime.now(timezone.utc)
        self.statistics_writer.reset(self.run_started_at)
        self._write_metadata()
        self._install_signal_handlers()

        logger.info(
            "Starting custom sender with %s seconds and %s planned requests from %s using max_inflight=%s "
            "dispatch_mode=%s timeout=%.3fs target=%s",
            self.total_points,
            self.total_planned_requests,
            self.config.script_path,
            self.config.max_inflight,
            self.config.dispatch_mode,
            self.config.request_timeout_seconds,
            self.config.target_host,
        )
        logger.info("Workload operations enabled: %s", ", ".join(self.workload_planner.operation_names()))

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
            self._progress_task = asyncio.create_task(self._progress_loop())
            loop = asyncio.get_running_loop()
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
                if self._progress_task is not None:
                    self._progress_task.cancel()
                    await asyncio.gather(self._progress_task, return_exceptions=True)

            if self.inflight_tasks:
                await asyncio.gather(*self.inflight_tasks, return_exceptions=True)

        self.report_writer.flush_closed(final=True)
        self.statistics_writer.flush_closed(final=True)
        logger.info(
            "Run complete: total_planned=%s planned_so_far=%s scheduled=%s started=%s completed=%s failed=%s timed_out=%s dropped_capacity=%s inflight=%s",
            self.total_planned_requests,
            self.planned_requests_so_far,
            self.scheduled_requests,
            self.started_requests,
            self.completed_requests,
            self.failed_requests,
            self.timed_out_requests,
            self.dropped_due_to_capacity,
            self.inflight_count,
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
        self.statistics_writer.record(planned_second_bucket, "planned", request_count)
        self.planned_requests_so_far += request_count
        if request_count <= 0:
            return

        if self.config.dispatch_mode == "burst" or request_count == 1:
            for request_index in range(request_count):
                self._launch_if_capacity(session, second_index, request_index)
        else:
            loop = asyncio.get_running_loop()
            second_start = start_monotonic + float(second_index)
            for request_index in range(request_count):
                scheduled_at = second_start + (request_index / request_count)
                remaining = scheduled_at - loop.time()
                if remaining > 0:
                    await asyncio.sleep(remaining)
                self._launch_if_capacity(session, second_index, request_index)

        self._flush_request_report_if_due()

    def _launch_if_capacity(
        self,
        session: "aiohttp.ClientSession",
        second_index: int,
        request_index: int,
    ) -> None:
        second_bucket = _second_bucket_now()
        scheduled_index = self.scheduled_requests
        self.scheduled_requests += 1
        self.statistics_writer.record(second_bucket, "scheduled")

        request = self.workload_planner.build_request(
            scheduled_index=scheduled_index,
            second_index=second_index,
            request_index_within_second=request_index,
        )

        try:
            token = self.token_queue.get_nowait()
        except asyncio.QueueEmpty:
            self.dropped_due_to_capacity += 1
            self.statistics_writer.record(second_bucket, "dropped_capacity")
            return

        self.started_requests += 1
        self.report_writer.record(second_bucket, request.report_url)
        self.statistics_writer.record(second_bucket, "started")

        task = asyncio.create_task(self._execute_request(session, token, request))
        self.inflight_tasks.add(task)
        task.add_done_callback(self.inflight_tasks.discard)

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
        except Exception:
            logger.exception("Unhandled request failure for %s %s", request.method, request.path)
            self.failed_requests += 1
            self.statistics_writer.record(_second_bucket_now(), "failed")
        finally:
            self.token_queue.put_nowait(token)

    async def _progress_loop(self) -> None:
        while not self.stop_requested.is_set():
            await asyncio.sleep(self.config.progress_log_interval_sec)
            self.report_writer.flush_closed()
            self.statistics_writer.flush_closed()
            percentage = (self.dispatched_seconds / max(self.total_points, 1)) * 100
            logger.info(
                "Progress %.1f%% (%s/%s seconds) total_planned=%s planned_so_far=%s scheduled=%s started=%s completed=%s failed=%s timed_out=%s dropped_capacity=%s inflight=%s",
                percentage,
                self.dispatched_seconds,
                self.total_points,
                self.total_planned_requests,
                self.planned_requests_so_far,
                self.scheduled_requests,
                self.started_requests,
                self.completed_requests,
                self.failed_requests,
                self.timed_out_requests,
                self.dropped_due_to_capacity,
                self.inflight_count,
            )

    def _flush_request_report_if_due(self) -> None:
        now = asyncio.get_running_loop().time()
        if (now - self._last_flush_monotonic) < self.config.request_log_flush_interval_sec:
            return

        self.report_writer.flush_closed()
        self.statistics_writer.flush_closed()
        self._last_flush_monotonic = now

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


def main() -> int:
    configure_logging()
    try:
        return asyncio.run(async_main())
    except KeyboardInterrupt:
        logger.warning("Interrupted by user.")
        return 130
    except Exception:
        logger.exception("Custom load sender failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
