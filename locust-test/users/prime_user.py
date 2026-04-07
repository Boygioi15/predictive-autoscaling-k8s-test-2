import os
import random
import time
import logging
import csv
import json

import gevent
from locust import HttpUser, task, constant
from gevent.lock import Semaphore

logging.basicConfig(level=logging.INFO)

CSV_LOG_PATH = os.getenv("PRIME_CSV_LOG_PATH", "./request-log.csv")
CSV_DEBOUNCE_SECONDS = 0.01
CSV_DEFAULT_TIME_TAKEN = "5"
_csv_lock = Semaphore()


def _get_interval(env_name: str, default: float) -> float:
    value = os.getenv(env_name, str(default))
    try:
        return max(0.0, float(value))
    except ValueError:
        return default


def _get_int(env_name: str, default: int) -> int:
    value = os.getenv(env_name, str(default))
    try:
        return int(value)
    except ValueError:
        return default


def _get_int_range(min_env_name: str, max_env_name: str, default_min: int, default_max: int):
    min_value = _get_int(min_env_name, default_min)
    max_value = _get_int(max_env_name, default_max)

    if min_value > max_value:
        return max_value, min_value

    return min_value, max_value


def _extract_csv_values(response_text: str):
    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError:
        return response_text, CSV_DEFAULT_TIME_TAKEN

    value = payload
    for key in ("result", "totalPrimesFound", "isPrime", "message"):
        if key in payload:
            value = payload[key]
            break

    time_taken = str(payload.get("timeTaken", CSV_DEFAULT_TIME_TAKEN)).replace("ms", "").strip() or CSV_DEFAULT_TIME_TAKEN
    return value, time_taken


def _append_csv_row(path: str, value, time_taken: str):
    with _csv_lock:
        gevent.sleep(CSV_DEBOUNCE_SECONDS)
        file_exists = os.path.exists(CSV_LOG_PATH)
        with open(CSV_LOG_PATH, "a", newline="", encoding="utf-8") as csv_file:
            writer = csv.writer(csv_file)
            if not file_exists:
                writer.writerow(["path", "value", "timeTaken"])
            writer.writerow([path, value, time_taken])

class PrimeUser(HttpUser):
    abstract = True
    host = "http://autoscaling-k8s-test"
    wait_time = constant(0)

    range_interval = _get_interval("PRIME_RANGE_INTERVAL", 2.0)
    kth_interval = _get_interval("PRIME_KTH_INTERVAL", 2.0)
    check_interval = _get_interval("PRIME_CHECK_INTERVAL", 2.0)
    range_min, range_max = _get_int_range("PRIME_RANGE_MIN", "PRIME_RANGE_MAX", 1_000, 500_000)
    kth_min, kth_max = _get_int_range("PRIME_KTH_MIN", "PRIME_KTH_MAX", 1_000, 50_000)
    check_min, check_max = _get_int_range("PRIME_CHECK_MIN", "PRIME_CHECK_MAX", 5_000_000, 100_000_000)

    def on_start(self):
        self._last_run_at = {}

    def _wait_for_task_interval(self, task_name: str, interval: float):
        now = time.monotonic()
        last_run_at = self._last_run_at.get(task_name)

        if last_run_at is not None:
            gevent.sleep(max(0.0, interval - (now - last_run_at)))

        self._last_run_at[task_name] = time.monotonic()


    @task(1)
    def range_prime(self):
        n = random.randint(self.range_min, self.range_max)
        response = self.client.get(
            f"/api/prime/range?n={n}",
            name="/prime/range"
        )
        value, time_taken = _extract_csv_values(response.text)
        _append_csv_row("/prime/range", value, time_taken)
        self._wait_for_task_interval("range_prime", self.range_interval)

    @task(1)
    def kth_prime(self):
        k = random.randint(self.kth_min, self.kth_max)
        response = self.client.get(
            f"/api/prime/kth?k={k}",
            name="/prime/kth"
        )
        value, time_taken = _extract_csv_values(response.text)
        _append_csv_row("/prime/kth", value, time_taken)
        self._wait_for_task_interval("kth_prime", self.kth_interval)

    @task(1)
    def check_prime(self):
        n = random.randint(self.check_min, self.check_max)
        response = self.client.get(
            f"/api/prime/check?n={n}",
            name="/prime/check"
        )
        value, time_taken = _extract_csv_values(response.text)
        _append_csv_row("/prime/check", value, time_taken)
        self._wait_for_task_interval("check_prime", self.check_interval)
