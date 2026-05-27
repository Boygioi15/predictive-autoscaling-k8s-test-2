import csv
import json
import logging
import os
import random
from dataclasses import dataclass
from typing import Callable, Protocol

import gevent
from gevent.lock import Semaphore

from utils.payload import random_text

logger = logging.getLogger(__name__)

DEFAULT_TARGET_HOST = os.getenv("TARGET_HOST", "http://autoscaling-k8s-test")
CSV_LOG_PATH = os.getenv("PRIME_CSV_LOG_PATH", "./request-log.csv")
CSV_DEBOUNCE_SECONDS = 0.01
CSV_DEFAULT_TIME_TAKEN = "5"
REQUEST_CSV_LOG_ENABLED = os.getenv("REQUEST_CSV_LOG_ENABLED", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
_csv_lock = Semaphore()


class RequestClient(Protocol):
    def get(self, url: str, **kwargs):
        ...

    def post(self, url: str, **kwargs):
        ...


@dataclass(frozen=True)
class ScriptOperation:
    name: str
    weight: int
    execute: Callable[[RequestClient, dict[str, str] | None], object]


def _get_int(env_name: str, default: int) -> int:
    value = os.getenv(env_name, str(default))
    try:
        return int(value)
    except ValueError:
        return default


def _get_int_range(min_env_name: str, max_env_name: str, default_min: int, default_max: int) -> tuple[int, int]:
    min_value = _get_int(min_env_name, default_min)
    max_value = _get_int(max_env_name, default_max)

    if min_value > max_value:
        return max_value, min_value

    return min_value, max_value


def _extract_csv_values(response_text: str) -> tuple[object, str]:
    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError:
        return response_text, CSV_DEFAULT_TIME_TAKEN

    value = payload
    for key in ("result", "totalPrimesFound", "isPrime", "message"):
        if key in payload:
            value = payload[key]
            break

    time_taken = str(payload.get("timeTaken", CSV_DEFAULT_TIME_TAKEN)).replace("ms", "").strip()
    return value, time_taken or CSV_DEFAULT_TIME_TAKEN


def _append_csv_row(log_path: str, path: str, value: object, time_taken: str) -> None:
    with _csv_lock:
        gevent.sleep(CSV_DEBOUNCE_SECONDS)
        file_exists = os.path.exists(log_path)
        with open(log_path, "a", newline="", encoding="utf-8") as csv_file:
            writer = csv.writer(csv_file)
            if not file_exists:
                writer.writerow(["path", "value", "timeTaken"])
            writer.writerow([path, value, time_taken])


def range_prime_request(client: RequestClient, headers: dict[str, str] | None = None):
    range_min, range_max = _get_int_range("PRIME_RANGE_MIN", "PRIME_RANGE_MAX", 1_000, 500_000)
    n = random.randint(range_min, range_max)
    response = client.get(f"/api/prime/range?n={n}", name="/prime/range", headers=headers)
    if REQUEST_CSV_LOG_ENABLED:
        value, time_taken = _extract_csv_values(response.text)
        _append_csv_row(CSV_LOG_PATH, "/prime/range", value, time_taken)
    return response


def kth_prime_request(client: RequestClient, headers: dict[str, str] | None = None):
    kth_min, kth_max = _get_int_range("PRIME_KTH_MIN", "PRIME_KTH_MAX", 1_000, 50_000)
    k = random.randint(kth_min, kth_max)
    response = client.get(f"/api/prime/kth?k={k}", name="/prime/kth", headers=headers)
    if REQUEST_CSV_LOG_ENABLED:
        value, time_taken = _extract_csv_values(response.text)
        _append_csv_row(CSV_LOG_PATH, "/prime/kth", value, time_taken)
    return response


def check_prime_request(client: RequestClient, headers: dict[str, str] | None = None):
    check_min, check_max = _get_int_range("PRIME_CHECK_MIN", "PRIME_CHECK_MAX", 5_000_000, 100_000_000)
    n = random.randint(check_min, check_max)
    response = client.get(f"/api/prime/check?n={n}", name="/prime/check", headers=headers)
    if REQUEST_CSV_LOG_ENABLED:
        value, time_taken = _extract_csv_values(response.text)
        _append_csv_row(CSV_LOG_PATH, "/prime/check", value, time_taken)
    return response


def analyze_text_request(client: RequestClient, headers: dict[str, str] | None = None):
    text = random_text(1000)
    return client.post("/text/analyze", json={"text": text}, name="/text/analyze", headers=headers)


def transform_text_request(client: RequestClient, headers: dict[str, str] | None = None):
    text = random_text(200)
    return client.post(
        "/text/transform?rounds=50",
        json={"text": text},
        name="/text/transform",
        headers=headers,
    )


def build_script_operation_cycle() -> list[ScriptOperation]:
    prime_weight = max(0, _get_int("PRIME_USER_WEIGHT", 1))
    text_weight = max(0, _get_int("TEXT_USER_WEIGHT", 2))
    operations = []

    if prime_weight > 0:
        operations.extend(
            [
                ScriptOperation("prime-range", prime_weight, range_prime_request),
                ScriptOperation("prime-kth", prime_weight, kth_prime_request),
                ScriptOperation("prime-check", prime_weight, check_prime_request),
            ]
        )

    if text_weight > 0:
        operations.extend(
            [
                ScriptOperation("text-analyze", text_weight, analyze_text_request),
                ScriptOperation("text-transform", text_weight, transform_text_request),
            ]
        )

    if not operations:
        raise ValueError("At least one of PRIME_USER_WEIGHT or TEXT_USER_WEIGHT must be greater than 0")

    cycle = []
    for operation in operations:
        cycle.extend([operation] * operation.weight)

    seed = _get_int("SCRIPT_RANDOM_SEED", 42)
    random.Random(seed).shuffle(cycle)
    return cycle
