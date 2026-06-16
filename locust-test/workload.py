import logging
import os
import random
from typing import Protocol

from utils.payload import random_text

logger = logging.getLogger(__name__)

DEFAULT_TARGET_HOST = os.getenv("TARGET_HOST", "http://autoscaling-k8s-test")

class RequestClient(Protocol):
    def get(self, url: str, **kwargs):
        ...

    def post(self, url: str, **kwargs):
        ...


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


def _request(client: RequestClient, method: str, url: str, **kwargs):
    kwargs.setdefault("stream", True)
    request_method = getattr(client, method)
    return request_method(url, **kwargs)


def range_prime_request(client: RequestClient):
    range_min, range_max = _get_int_range("PRIME_RANGE_MIN", "PRIME_RANGE_MAX", 1_000, 500_000)
    n = random.randint(range_min, range_max)
    return _request(
        client,
        "get",
        f"/api/prime/range?n={n}",
        name="/prime/range",
    )


def kth_prime_request(client: RequestClient):
    kth_min, kth_max = _get_int_range("PRIME_KTH_MIN", "PRIME_KTH_MAX", 1_000, 50_000)
    k = random.randint(kth_min, kth_max)
    return _request(
        client,
        "get",
        f"/api/prime/kth?k={k}",
        name="/prime/kth",
    )


def check_prime_request(client: RequestClient):
    check_min, check_max = _get_int_range("PRIME_CHECK_MIN", "PRIME_CHECK_MAX", 5_000_000, 100_000_000)
    n = random.randint(check_min, check_max)
    return _request(
        client,
        "get",
        f"/api/prime/check?n={n}",
        name="/prime/check",
    )


def analyze_text_request(client: RequestClient):
    text = random_text(1000)
    return _request(
        client,
        "post",
        "/text/analyze",
        json={"text": text},
        name="/text/analyze",
    )


def transform_text_request(client: RequestClient):
    text = random_text(200)
    return _request(
        client,
        "post",
        "/text/transform?rounds=50",
        json={"text": text},
        name="/text/transform",
    )
