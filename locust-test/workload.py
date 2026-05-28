import csv
import logging
import os
import random
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Protocol

import gevent
from gevent.lock import Semaphore

from utils.payload import random_text

logger = logging.getLogger(__name__)

DEFAULT_TARGET_HOST = os.getenv("TARGET_HOST", "http://autoscaling-k8s-test")
CSV_LOG_PATH = os.getenv("REQUEST_LOG_PATH", "./request-log.csv")
REQUEST_CSV_LOG_ENABLED = os.getenv("REQUEST_CSV_LOG_ENABLED", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
_csv_lock = Semaphore()
_request_counts: dict[tuple[str, str], int] = defaultdict(int)
_flushed_keys: set[tuple[str, str]] = set()


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


def _record_request(url: str, time_sent: str) -> None:
    second_bucket = time_sent[:19] + "Z"

    with _csv_lock:
        _request_counts[(second_bucket, url)] += 1


def reset_request_logs(log_path: str = CSV_LOG_PATH) -> None:
    with _csv_lock:
        _request_counts.clear()
        _flushed_keys.clear()

    log_file = Path(log_path)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(["second", "url", "count"])


def flush_request_logs(log_path: str = CSV_LOG_PATH, final: bool = False) -> None:
    with _csv_lock:
        current_second = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        rows_to_flush = []
        for key, count in sorted(_request_counts.items()):
            second_bucket, url = key
            if key in _flushed_keys:
                continue
            if not final and second_bucket >= current_second:
                continue
            rows_to_flush.append((second_bucket, url, int(count)))
            _flushed_keys.add(key)

    if not rows_to_flush:
        return

    log_file = Path(log_path)
    with log_file.open("a", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        for second_bucket, url, count in rows_to_flush:
            writer.writerow([second_bucket, url, count])


def _request_and_log(client: RequestClient, method: str, url: str, **kwargs):
    time_sent = datetime.now(timezone.utc).isoformat()
    if REQUEST_CSV_LOG_ENABLED:
        _record_request(url, time_sent)
    request_method = getattr(client, method)
    return request_method(url, **kwargs)


def range_prime_request(client: RequestClient, headers: dict[str, str] | None = None):
    range_min, range_max = _get_int_range("PRIME_RANGE_MIN", "PRIME_RANGE_MAX", 1_000, 500_000)
    n = random.randint(range_min, range_max)
    return _request_and_log(
        client,
        "get",
        f"/api/prime/range?n={n}",
        name="/prime/range",
        headers=headers,
    )


def kth_prime_request(client: RequestClient, headers: dict[str, str] | None = None):
    kth_min, kth_max = _get_int_range("PRIME_KTH_MIN", "PRIME_KTH_MAX", 1_000, 50_000)
    k = random.randint(kth_min, kth_max)
    return _request_and_log(
        client,
        "get",
        f"/api/prime/kth?k={k}",
        name="/prime/kth",
        headers=headers,
    )


def check_prime_request(client: RequestClient, headers: dict[str, str] | None = None):
    check_min, check_max = _get_int_range("PRIME_CHECK_MIN", "PRIME_CHECK_MAX", 5_000_000, 100_000_000)
    n = random.randint(check_min, check_max)
    return _request_and_log(
        client,
        "get",
        f"/api/prime/check?n={n}",
        name="/prime/check",
        headers=headers,
    )


def analyze_text_request(client: RequestClient, headers: dict[str, str] | None = None):
    text = random_text(1000)
    return _request_and_log(
        client,
        "post",
        "/text/analyze",
        json={"text": text},
        name="/text/analyze",
        headers=headers,
    )


def transform_text_request(client: RequestClient, headers: dict[str, str] | None = None):
    text = random_text(200)
    return _request_and_log(
        client,
        "post",
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
