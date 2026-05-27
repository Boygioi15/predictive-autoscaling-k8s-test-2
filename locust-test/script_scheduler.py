import csv
import logging
import os
import time
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import gevent
from gevent.event import Event
from gevent.lock import Semaphore
from locust import User, constant, events, task
from locust.clients import HttpSession

from workload import DEFAULT_TARGET_HOST, build_script_operation_cycle

logger = logging.getLogger(__name__)

_active_scheduler = None


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

        self.start_time = _parse_timestamp(os.getenv("SCRIPT_START_TIME", ""), "SCRIPT_START_TIME")
        self.end_time = _parse_timestamp(os.getenv("SCRIPT_END_TIME", ""), "SCRIPT_END_TIME")
        if self.end_time < self.start_time:
            raise ValueError("SCRIPT_END_TIME must be greater than or equal to SCRIPT_START_TIME")

        self.dispatch_mode = os.getenv("SCRIPT_DISPATCH_MODE", "spread").strip().lower()
        if self.dispatch_mode not in {"spread", "burst"}:
            raise ValueError("SCRIPT_DISPATCH_MODE must be either 'spread' or 'burst'")

        self.progress_log_interval = int(os.getenv("SCRIPT_PROGRESS_LOG_INTERVAL", "10"))
        self.metrics_flush_interval = max(1, int(os.getenv("SCRIPT_METRICS_FLUSH_INTERVAL_SEC", "60")))
        self.script_metrics_path = Path(
            os.getenv("SCRIPT_METRICS_PATH", Path(__file__).resolve().parent / "script-metrics.csv")
        )
        self.wall_metrics_path = Path(
            os.getenv("SCRIPT_WALL_METRICS_PATH", Path(__file__).resolve().parent / "script-wall-metrics.csv")
        )
        self.client = HttpSession(
            base_url=os.getenv("TARGET_HOST", DEFAULT_TARGET_HOST),
            request_event=self.environment.events.request,
            user=_ScriptUserShim(),
        )
        self.client.trust_env = False

        self.timeline = self._load_timeline()
        self.operation_cycle = build_script_operation_cycle()
        self.operation_index = 0
        self.greenlets = []
        self.stop_event = Event()
        self.counter_lock = Semaphore()

        self.total_points = len(self.timeline)
        self.total_planned_requests = sum(request_count for _, request_count in self.timeline)
        self.dispatched_requests = 0
        self.completed_requests = 0
        self.failed_requests = 0
        self.script_second_stats = {
            timestamp: {
                "planned": request_count,
                "dispatched": 0,
                "completed": 0,
                "failed": 0,
            }
            for timestamp, request_count in self.timeline
        }
        self.wall_second_stats = defaultdict(
            lambda: {
                "dispatched": 0,
                "completed": 0,
                "failed": 0,
            }
        )
        self._greenlet = None
        self._last_metrics_flush = 0.0

    def start(self):
        logger.info(
            "Starting script scheduler with %s seconds and %s planned requests from %s",
            self.total_points,
            self.total_planned_requests,
            self.script_path,
        )
        self._last_metrics_flush = time.perf_counter()
        self._write_metrics_files()
        self._greenlet = gevent.spawn(self._run)

    def stop(self):
        self.stop_event.set()
        for greenlet in self.greenlets:
            if not greenlet.dead:
                greenlet.kill(block=False)
        if self._greenlet is not None and not self._greenlet.dead:
            self._greenlet.kill(block=False)
        self._write_metrics_files()

    def _load_timeline(self) -> list[tuple[datetime, int]]:
        if not self.script_path.exists():
            raise FileNotFoundError(f"Script CSV not found: {self.script_path}")

        timeline = {}
        with self.script_path.open(newline="", encoding="utf-8") as csv_file:
            reader = csv.DictReader(csv_file)
            required_columns = {"datetime", "requests"}
            if not reader.fieldnames or not required_columns.issubset(reader.fieldnames):
                raise ValueError(
                    f"CSV must contain columns {sorted(required_columns)}, got {reader.fieldnames}"
                )

            for row in reader:
                row_time = _parse_timestamp(row["datetime"], "CSV datetime")
                if row_time < self.start_time or row_time > self.end_time:
                    continue

                requests_value = max(0, int(float(row["requests"])))
                timeline[row_time] = timeline.get(row_time, 0) + requests_value

        if not timeline:
            raise ValueError("No CSV rows found inside the configured SCRIPT_START_TIME/SCRIPT_END_TIME range")

        ordered_timeline = []
        current_time = self.start_time
        while current_time <= self.end_time:
            ordered_timeline.append((current_time, timeline.get(current_time, 0)))
            current_time += timedelta(seconds=1)

        return ordered_timeline

    def _run(self):
        start_monotonic = time.perf_counter()

        for second_index, (timestamp, request_count) in enumerate(self.timeline):
            if self.stop_event.is_set():
                return

            target_offset = float(second_index)
            remaining = (start_monotonic + target_offset) - time.perf_counter()
            if remaining > 0:
                gevent.sleep(remaining)

            self._dispatch_second(timestamp, request_count)
            self._flush_metrics_if_due()
            if self._should_log_progress(second_index):
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
        self._write_metrics_files()
        if self.environment.runner is not None and not self.stop_event.is_set():
            if _script_web_ui_enabled():
                self.environment.runner.stop()
            else:
                self.environment.runner.quit()

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
        dispatch_second = dispatch_time.replace(microsecond=0)
        request_headers = {
            "X-Locust-Request-Id": str(uuid.uuid4()),
            "X-Locust-Script-Timestamp": timestamp.isoformat(),
            "X-Locust-Dispatch-Time": dispatch_time.isoformat(),
            "X-Locust-Operation": operation.name,
        }

        with self.counter_lock:
            self.script_second_stats[timestamp]["dispatched"] += 1
            self.wall_second_stats[dispatch_second]["dispatched"] += 1

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
                self.script_second_stats[timestamp]["failed"] += 1
                self.wall_second_stats[dispatch_second]["failed"] += 1
            return

        failed = getattr(response, "error", None) is not None or getattr(response, "status_code", 0) >= 400
        with self.counter_lock:
            if failed:
                self.failed_requests += 1
                self.script_second_stats[timestamp]["failed"] += 1
                self.wall_second_stats[dispatch_second]["failed"] += 1
            else:
                self.completed_requests += 1
                self.script_second_stats[timestamp]["completed"] += 1
                self.wall_second_stats[dispatch_second]["completed"] += 1

    def _next_operation(self):
        with self.counter_lock:
            operation = self.operation_cycle[self.operation_index % len(self.operation_cycle)]
            self.operation_index += 1
            return operation

    def _write_metrics_files(self) -> None:
        with self.counter_lock:
            script_rows = [
                (
                    timestamp,
                    self.script_second_stats[timestamp]["planned"],
                    self.script_second_stats[timestamp]["dispatched"],
                    self.script_second_stats[timestamp]["completed"],
                    self.script_second_stats[timestamp]["failed"],
                )
                for timestamp, _request_count in self.timeline
            ]
            wall_rows = [
                (
                    timestamp,
                    stats["dispatched"],
                    stats["completed"],
                    stats["failed"],
                )
                for timestamp, stats in sorted(self.wall_second_stats.items())
            ]

        self.script_metrics_path.parent.mkdir(parents=True, exist_ok=True)
        with self.script_metrics_path.open("w", newline="", encoding="utf-8") as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(
                [
                    "script_datetime",
                    "planned_requests",
                    "dispatched_requests",
                    "completed_requests",
                    "failed_requests",
                ]
            )
            for timestamp, planned, dispatched, completed, failed in script_rows:
                writer.writerow(
                    [
                        timestamp.isoformat(),
                        planned,
                        dispatched,
                        completed,
                        failed,
                    ]
                )

        self.wall_metrics_path.parent.mkdir(parents=True, exist_ok=True)
        with self.wall_metrics_path.open("w", newline="", encoding="utf-8") as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(
                [
                    "wall_clock_second",
                    "dispatched_requests",
                    "completed_requests",
                    "failed_requests",
                ]
            )
            for timestamp, dispatched, completed, failed in wall_rows:
                writer.writerow(
                    [
                        timestamp.isoformat(),
                        dispatched,
                        completed,
                        failed,
                    ]
                )

        logger.info("Wrote script metrics to %s", self.script_metrics_path)
        logger.info("Wrote wall-clock metrics to %s", self.wall_metrics_path)
        self._last_metrics_flush = time.perf_counter()

    def _flush_metrics_if_due(self) -> None:
        if (time.perf_counter() - self._last_metrics_flush) < self.metrics_flush_interval:
            return
        self._write_metrics_files()

    def _should_log_progress(self, index: int) -> bool:
        # if index == 0 or index == self.total_points - 1:
        #     return True
        # if self.progress_log_interval <= 0:
        #     return False
        # return index % self.progress_log_interval == 0
        return True


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
