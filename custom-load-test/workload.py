from __future__ import annotations

import hashlib
import os
import random
import string
from dataclasses import dataclass


@dataclass(frozen=True)
class PreparedRequest:
    method: str
    path: str
    report_url: str
    json_body: dict[str, object] | None = None


@dataclass(frozen=True)
class OperationDefinition:
    name: str
    weight: int


@dataclass(frozen=True)
class WorkloadConfig:
    seed: int
    prime_user_weight: int
    text_user_weight: int
    prime_range_min: int
    prime_range_max: int
    prime_kth_min: int
    prime_kth_max: int
    prime_check_min: int
    prime_check_max: int
    prime_base_path: str
    text_base_path: str
    text_transform_rounds: int
    analyze_text_size: int
    transform_text_size: int


def _get_int(env_name: str, default: int) -> int:
    raw_value = os.getenv(env_name, str(default))
    try:
        return int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{env_name} must be an integer, got: {raw_value!r}") from exc


def _get_int_range(min_env_name: str, max_env_name: str, default_min: int, default_max: int) -> tuple[int, int]:
    min_value = _get_int(min_env_name, default_min)
    max_value = _get_int(max_env_name, default_max)
    if min_value <= max_value:
        return min_value, max_value
    return max_value, min_value


def _normalize_base_path(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError("Base path must not be empty")
    if not stripped.startswith("/"):
        stripped = f"/{stripped}"
    return stripped.rstrip("/")


def load_workload_config() -> WorkloadConfig:
    prime_range_min, prime_range_max = _get_int_range("PRIME_RANGE_MIN", "PRIME_RANGE_MAX", 1_000, 500_000)
    prime_kth_min, prime_kth_max = _get_int_range("PRIME_KTH_MIN", "PRIME_KTH_MAX", 1_000, 50_000)
    prime_check_min, prime_check_max = _get_int_range("PRIME_CHECK_MIN", "PRIME_CHECK_MAX", 5_000_000, 100_000_000)

    return WorkloadConfig(
        seed=_get_int("SCRIPT_RANDOM_SEED", 42),
        prime_user_weight=max(0, _get_int("PRIME_USER_WEIGHT", 1)),
        text_user_weight=max(0, _get_int("TEXT_USER_WEIGHT", 2)),
        prime_range_min=prime_range_min,
        prime_range_max=prime_range_max,
        prime_kth_min=prime_kth_min,
        prime_kth_max=prime_kth_max,
        prime_check_min=prime_check_min,
        prime_check_max=prime_check_max,
        prime_base_path=_normalize_base_path(os.getenv("PRIME_BASE_PATH", "/api/prime")),
        text_base_path=_normalize_base_path(os.getenv("TEXT_BASE_PATH", "/api/text")),
        text_transform_rounds=max(1, _get_int("TEXT_TRANSFORM_ROUNDS", 50)),
        analyze_text_size=max(1, _get_int("TEXT_ANALYZE_SIZE", 1_000)),
        transform_text_size=max(1, _get_int("TEXT_TRANSFORM_SIZE", 200)),
    )


class WorkloadPlanner:
    def __init__(self, config: WorkloadConfig):
        self.config = config
        self._cycle = self._build_cycle()

    def _build_cycle(self) -> list[OperationDefinition]:
        prime_weight = self.config.prime_user_weight
        text_weight = self.config.text_user_weight
        operations: list[OperationDefinition] = []

        if prime_weight > 0:
            operations.extend(
                [
                    OperationDefinition("prime-range", prime_weight),
                    OperationDefinition("prime-kth", prime_weight),
                    OperationDefinition("prime-check", prime_weight),
                ]
            )

        if text_weight > 0:
            operations.extend(
                [
                    OperationDefinition("text-analyze", text_weight),
                    OperationDefinition("text-transform", text_weight),
                ]
            )

        if not operations:
            raise ValueError("At least one of PRIME_USER_WEIGHT or TEXT_USER_WEIGHT must be greater than 0")

        cycle: list[OperationDefinition] = []
        for operation in operations:
            cycle.extend([operation] * operation.weight)

        random.Random(self.config.seed).shuffle(cycle)
        return cycle

    def operation_names(self) -> list[str]:
        return sorted({operation.name for operation in self._cycle})

    def build_request(
        self,
        scheduled_index: int,
        second_index: int,
        request_index_within_second: int,
    ) -> PreparedRequest:
        operation = self._cycle[scheduled_index % len(self._cycle)]
        rng = random.Random(self._request_seed(operation.name, second_index, request_index_within_second, scheduled_index))

        if operation.name == "prime-range":
            n = rng.randint(self.config.prime_range_min, self.config.prime_range_max)
            return PreparedRequest(
                method="GET",
                path=f"{self.config.prime_base_path}/range?n={n}",
                report_url=f"{self.config.prime_base_path}/range",
            )

        if operation.name == "prime-kth":
            k = rng.randint(self.config.prime_kth_min, self.config.prime_kth_max)
            return PreparedRequest(
                method="GET",
                path=f"{self.config.prime_base_path}/kth?k={k}",
                report_url=f"{self.config.prime_base_path}/kth",
            )

        if operation.name == "prime-check":
            n = rng.randint(self.config.prime_check_min, self.config.prime_check_max)
            return PreparedRequest(
                method="GET",
                path=f"{self.config.prime_base_path}/check?n={n}",
                report_url=f"{self.config.prime_base_path}/check",
            )

        if operation.name == "text-analyze":
            return PreparedRequest(
                method="POST",
                path=f"{self.config.text_base_path}/text/analyze",
                report_url=f"{self.config.text_base_path}/text/analyze",
                json_body={"text": _random_text(rng, self.config.analyze_text_size)},
            )

        if operation.name == "text-transform":
            return PreparedRequest(
                method="POST",
                path=f"{self.config.text_base_path}/text/transform?rounds={self.config.text_transform_rounds}",
                report_url=f"{self.config.text_base_path}/text/transform",
                json_body={"text": _random_text(rng, self.config.transform_text_size)},
            )

        raise ValueError(f"Unsupported operation: {operation.name}")

    def _request_seed(
        self,
        operation_name: str,
        second_index: int,
        request_index_within_second: int,
        scheduled_index: int,
    ) -> int:
        payload = (
            f"{self.config.seed}:{operation_name}:{second_index}:{request_index_within_second}:{scheduled_index}"
        ).encode("utf-8")
        digest = hashlib.blake2b(payload, digest_size=8).digest()
        return int.from_bytes(digest, "big")


def _random_text(rng: random.Random, size: int) -> str:
    word_count = max(1, size // 5)
    words = []
    for _ in range(word_count):
        word = "".join(rng.choice(string.ascii_lowercase) for _ in range(5))
        words.append(word)
    return " ".join(words)
