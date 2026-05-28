import csv
import logging
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import gevent
from gevent.event import Event
from gevent.lock import Semaphore
from locust import User, constant, events, task
from locust.clients import HttpSession

from workload import DEFAULT_TARGET_HOST, build_script_operation_cycle, flush_request_logs, reset_request_logs

logger = logging.getLogger(__name__)

_active_scheduler = None

RUN_METADATA_PATH = os.getenv("RUN_METADATA_PATH", "../shares/locust_run_metadata.csv")


def _script_web_ui_enabled() -> bool:
    return os.getenv("SCRIPT_WEB_UI", "true").split()[0].strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _parse_timestamp(value: str, env_name: str) -> datetime:
    try:
        return datetime.fromisoformat(value.strip())
    except ValueError as exc:
        raise ValueError(f"{env_name} must be an ISO-8601 datetime, got: {value!r}") from exc


class _ScriptUserShim:
    def context(self) -> dict[str, str]:
        return {"mode": "script"}


class ScriptDriverUser(User):
    fixed_count = 1
    weight = 0
    wait_time = constant(3600)
    host = DEFAULT_TARGET_HOST

    @task
    def park(self):
        gevent.sleep(3600)


class ScriptScheduler:
    def __init__(self, environment):
        self.environment = environment
        configured_path = Path(os.getenv("SCRIPT_CSV_PATH", "script.csv"))
        if configured_path.is_absolute():
            self.script_path = configured_path
        else:
            self.script_path = Path(__file__).resolve().parent / configured_path

        self.dispatch_mode = os.getenv("SCRIPT_DISPATCH_MODE", "spread").strip().lower()
        if self.dispatch_mode not in {"spread", "burst"}:
            raise ValueError("SCRIPT_DISPATCH_MODE must be either 'spread' or 'burst'")
        self.request_log_flush_interval = max(1, int(os.getenv("REQUEST_LOG_FLUSH_INTERVAL_SEC", "60")))

        self.client = HttpSession(
            base_url=os.getenv("TARGET_HOST", DEFAULT_TARGET_HOST),
            request_event=self.environment.events.request,
            user=_ScriptUserShim(),
        )
        self.client.trust_env = False

        self.timeline = self._load_timeline()
        self.start_time = self.timeline[0][0]
        self.end_time = self.timeline[-1][0]
        self.operation_cycle = build_script_operation_cycle()
        self.operation_index = 0
        self.greenlets = []
        self.stop_event = Event()
        self.counter_lock = Semaphore()
        self.run_metadata_path = self._resolve_output_path(RUN_METADATA_PATH)

        self.total_points = len(self.timeline)
        self.total_planned_requests = sum(request_count for _, request_count in self.timeline)
        self.dispatched_requests = 0
        self.completed_requests = 0
        self.failed_requests = 0
        self._greenlet = None
        self._last_request_log_flush = 0.0
        self.run_started_at = None

    def _resolve_output_path(self, configured_path: str) -> Path:
        path = Path(configured_path)
        if path.is_absolute():
            return path
        return Path(__file__).resolve().parent / path

    def start(self):
        reset_request_logs()
        logger.info(
            "Starting script scheduler with %s seconds and %s planned requests from %s (%s -> %s)",
            self.total_points,
            self.total_planned_requests,
            self.script_path,
            self.start_time.isoformat(),
            self.end_time.isoformat(),
        )
        self._last_request_log_flush = time.perf_counter()
        self._greenlet = gevent.spawn(self._run)

    def stop(self):
        self.stop_event.set()
        for greenlet in self.greenlets:
            if not greenlet.dead:
                greenlet.kill(block=False)
        if self._greenlet is not None and not self._greenlet.dead:
            self._greenlet.kill(block=False)
        flush_request_logs(final=True)

    def _load_timeline(self) -> list[tuple[datetime, int]]:
        if not self.script_path.exists():
            raise FileNotFoundError(f"Script CSV not found: {self.script_path}")

        ordered_timeline = []
        current_time = None

        with self.script_path.open(newline="", encoding="utf-8") as csv_file:
            reader = csv.DictReader(csv_file)
            required_columns = {"datetime", "requests"}
            if not reader.fieldnames or not required_columns.issubset(reader.fieldnames):
                raise ValueError(
                    f"CSV must contain columns {sorted(required_columns)}, got {reader.fieldnames}"
                )

            for row in reader:
                row_time = _parse_timestamp(row["datetime"], "CSV datetime")
                requests_value = max(0, int(float(row["requests"])))

                if current_time is None:
                    current_time = row_time

                while current_time < row_time:
                    ordered_timeline.append((current_time, 0))
                    current_time += timedelta(seconds=1)

                ordered_timeline.append((row_time, requests_value))
                current_time = row_time + timedelta(seconds=1)

        if not ordered_timeline:
            raise ValueError("No CSV rows found in the script file")

        return ordered_timeline

    def _run(self):
        self.run_started_at = datetime.now(timezone.utc)
        self._write_run_metadata()
        start_monotonic = time.perf_counter()

        for second_index, (timestamp, request_count) in enumerate(self.timeline):
            if self.stop_event.is_set():
                return

            target_offset = float(second_index)
            remaining = (start_monotonic + target_offset) - time.perf_counter()
            if remaining > 0:
                gevent.sleep(remaining)

            self._dispatch_second(timestamp, request_count)
            self._flush_request_logs_if_due()
            percentage = ((second_index + 1) / max(self.total_points, 1)) * 100
            logger.info(
                "Script progress %.1f%% (%s/%s) timestamp=%s planned_requests=%s dispatched_so_far=%s completed=%s failed=%s",
                percentage,
                second_index + 1,
                self.total_points,
                timestamp.isoformat(),
                request_count,
                self.dispatched_requests,
                self.completed_requests,
                self.failed_requests,
            )

        gevent.joinall(self.greenlets)
        logger.info(
            "Script completed: planned=%s dispatched=%s completed=%s failed=%s",
            self.total_planned_requests,
            self.dispatched_requests,
            self.completed_requests,
            self.failed_requests,
        )
        flush_request_logs(final=True)
        if self.environment.runner is not None and not self.stop_event.is_set():
            if _script_web_ui_enabled():
                self.environment.runner.stop()
            else:
                self.environment.runner.quit()

    def _write_run_metadata(self) -> None:
        if self.run_started_at is None:
            return

        self.run_metadata_path.parent.mkdir(parents=True, exist_ok=True)
        run_start_second = self.run_started_at.replace(microsecond=0)
        with self.run_metadata_path.open("w", newline="", encoding="utf-8") as csv_file:
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
                    str(self.script_path),
                    self.start_time.isoformat(),
                    self.end_time.isoformat(),
                    self.total_points,
                    self.total_planned_requests,
                ]
            )

        logger.info(
            "Wrote Locust run metadata to %s with run_start_time=%s",
            self.run_metadata_path,
            self.run_started_at.isoformat(),
        )

    def _dispatch_second(self, timestamp: datetime, request_count: int) -> None:
        if request_count <= 0:
            return

        for request_index in range(request_count):
            operation = self._next_operation()
            delay = 0.0
            if self.dispatch_mode == "spread" and request_count > 1:
                delay = request_index / request_count

            greenlet = gevent.spawn_later(
                delay,
                self._send_request,
                timestamp,
                request_index + 1,
                operation,
            )
            self.greenlets.append(greenlet)

        with self.counter_lock:
            self.dispatched_requests += request_count

    def _send_request(self, timestamp: datetime, request_number: int, operation) -> None:
        if self.stop_event.is_set():
            return

        dispatch_time = datetime.now(self.start_time.tzinfo)
        request_headers = {
            "X-Locust-Request-Id": str(uuid.uuid4()),
            "X-Locust-Script-Timestamp": timestamp.isoformat(),
            "X-Locust-Dispatch-Time": dispatch_time.isoformat(),
            "X-Locust-Operation": operation.name,
        }

        try:
            response = operation.execute(self.client, headers=request_headers)
        except Exception:
            logger.exception(
                "Script request crashed at timestamp=%s request=%s operation=%s",
                timestamp.isoformat(),
                request_number,
                operation.name,
            )
            with self.counter_lock:
                self.failed_requests += 1
            return

        failed = getattr(response, "error", None) is not None or getattr(response, "status_code", 0) >= 400
        with self.counter_lock:
            if failed:
                self.failed_requests += 1
            else:
                self.completed_requests += 1

    def _next_operation(self):
        with self.counter_lock:
            operation = self.operation_cycle[self.operation_index % len(self.operation_cycle)]
            self.operation_index += 1
            return operation

    def _flush_request_logs_if_due(self) -> None:
        if (time.perf_counter() - self._last_request_log_flush) < self.request_log_flush_interval:
            return

        flush_request_logs()
        self._last_request_log_flush = time.perf_counter()


@events.test_start.add_listener
def _start_script_scheduler(environment, **kwargs):
    global _active_scheduler
    if os.getenv("MODE", "manual").split()[0].lower() != "script":
        return
    if _active_scheduler is not None:
        return

    _active_scheduler = ScriptScheduler(environment)
    _active_scheduler.start()


@events.test_stop.add_listener
def _stop_script_scheduler(environment, **kwargs):
    del environment
    global _active_scheduler
    if _active_scheduler is None:
        return

    _active_scheduler.stop()
    _active_scheduler = None
