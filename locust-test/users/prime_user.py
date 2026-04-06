import os
import random
import time
import logging

import gevent
from locust import HttpUser, task, constant

logging.basicConfig(level=logging.INFO)


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
        logging.info(f"Range prime result for n={n}: {response.text}")
        self._wait_for_task_interval("range_prime", self.range_interval)

    @task(1)
    def kth_prime(self):
        k = random.randint(self.kth_min, self.kth_max)
        response = self.client.get(
            f"/api/prime/kth?k={k}",
            name="/prime/kth"
        )
        logging.info(f"Kth prime result for k={k}: {response.text}")
        self._wait_for_task_interval("kth_prime", self.kth_interval)

    @task(1)
    def check_prime(self):
        n = random.randint(self.check_min, self.check_max)
        response = self.client.get(
            f"/api/prime/check?n={n}",
            name="/prime/check"
        )
        logging.info(f"Check prime result for n={n}: {response.text}")
        self._wait_for_task_interval("check_prime", self.check_interval)
