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
    memory_user_weight: int
    io_user_weight: int
    prime_range_min: int
    prime_range_max: int
    prime_kth_min: int
    prime_kth_max: int
    prime_check_min: int
    prime_check_max: int
    prime_base_path: str
    text_base_path: str
    io_base_path: str
    memory_text_size: int
    memory_chunk_size_kib: int
    memory_chunk_count: int
    memory_hold_ms: int
    io_read_min_kib: int
    io_read_max_kib: int
    io_write_min_kib: int
    io_write_max_kib: int
    io_file_slot_count: int
    io_segments: int
    io_hold_ms: int


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


def _get_weight(primary_env_name: str, fallback_env_name: str | None, default: int) -> int:
    raw_value = os.getenv(primary_env_name)
    if raw_value is None and fallback_env_name is not None:
        raw_value = os.getenv(fallback_env_name)
    if raw_value is None:
        raw_value = str(default)

    try:
        return max(0, int(raw_value))
    except ValueError as exc:
        raise ValueError(f"{primary_env_name} must be an integer, got: {raw_value!r}") from exc


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
    io_read_min_kib, io_read_max_kib = _get_int_range("IO_READ_MIN_KIB", "IO_READ_MAX_KIB", 128, 1024)
    io_write_min_kib, io_write_max_kib = _get_int_range("IO_WRITE_MIN_KIB", "IO_WRITE_MAX_KIB", 128, 1024)

    return WorkloadConfig(
        seed=_get_int("SCRIPT_RANDOM_SEED", 42),
        prime_user_weight=max(0, _get_int("PRIME_USER_WEIGHT", 1)),
        memory_user_weight=_get_weight("MEMORY_USER_WEIGHT", "TEXT_USER_WEIGHT", 2),
        io_user_weight=max(0, _get_int("IO_USER_WEIGHT", 0)),
        prime_range_min=prime_range_min,
        prime_range_max=prime_range_max,
        prime_kth_min=prime_kth_min,
        prime_kth_max=prime_kth_max,
        prime_check_min=prime_check_min,
        prime_check_max=prime_check_max,
        prime_base_path=_normalize_base_path(os.getenv("PRIME_BASE_PATH", "/api/prime")),
        text_base_path=_normalize_base_path(os.getenv("TEXT_BASE_PATH", "/api/text")),
        io_base_path=_normalize_base_path(os.getenv("IO_BASE_PATH", "/api/io")),
        memory_text_size=max(256, _get_int("MEMORY_TEXT_SIZE", 32_768)),
        memory_chunk_size_kib=max(32, _get_int("MEMORY_CHUNK_SIZE_KIB", 256)),
        memory_chunk_count=max(1, _get_int("MEMORY_CHUNK_COUNT", 12)),
        memory_hold_ms=max(0, _get_int("MEMORY_HOLD_MS", 25)),
        io_read_min_kib=io_read_min_kib,
        io_read_max_kib=io_read_max_kib,
        io_write_min_kib=io_write_min_kib,
        io_write_max_kib=io_write_max_kib,
        io_file_slot_count=max(1, _get_int("IO_FILE_SLOT_COUNT", 16)),
        io_segments=max(1, _get_int("IO_SEGMENTS", 4)),
        io_hold_ms=max(0, _get_int("IO_HOLD_MS", 10)),
    )


class WorkloadPlanner:
    def __init__(self, config: WorkloadConfig):
        self.config = config
        self._cycle = self._build_cycle()

    def _build_cycle(self) -> list[OperationDefinition]:
        prime_weight = self.config.prime_user_weight
        memory_weight = self.config.memory_user_weight
        io_weight = self.config.io_user_weight
        operations: list[OperationDefinition] = []

        if prime_weight > 0:
            operations.extend(
                [
                    OperationDefinition("prime-range", prime_weight),
                    OperationDefinition("prime-kth", prime_weight),
                    OperationDefinition("prime-check", prime_weight),
                ]
            )

        if memory_weight > 0:
            operations.append(OperationDefinition("text-pressure", memory_weight))

        if io_weight > 0:
            operations.extend(
                [
                    OperationDefinition("io-read", io_weight),
                    OperationDefinition("io-write", io_weight),
                ]
            )

        if not operations:
            raise ValueError(
                "At least one of PRIME_USER_WEIGHT, MEMORY_USER_WEIGHT/TEXT_USER_WEIGHT, or IO_USER_WEIGHT must be greater than 0"
            )

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

        if operation.name == "text-pressure":
            return PreparedRequest(
                method="POST",
                path=(
                    f"{self.config.text_base_path}/text/pressure"
                    f"?chunkSizeKb={self.config.memory_chunk_size_kib}"
                    f"&chunkCount={self.config.memory_chunk_count}"
                    f"&holdMs={self.config.memory_hold_ms}"
                ),
                report_url=f"{self.config.text_base_path}/text/pressure",
                json_body={"text": _random_text(rng, self.config.memory_text_size)},
            )

        if operation.name == "io-read":
            size_kib = rng.randint(self.config.io_read_min_kib, self.config.io_read_max_kib)
            file_id = f"slot-{rng.randint(0, self.config.io_file_slot_count - 1)}"
            return PreparedRequest(
                method="GET",
                path=f"{self.config.io_base_path}/io/read?fileId={file_id}&sizeKb={size_kib}&holdMs={self.config.io_hold_ms}",
                report_url=f"{self.config.io_base_path}/io/read",
            )

        if operation.name == "io-write":
            size_kib = rng.randint(self.config.io_write_min_kib, self.config.io_write_max_kib)
            file_id = f"slot-{rng.randint(0, self.config.io_file_slot_count - 1)}"
            return PreparedRequest(
                method="POST",
                path=(
                    f"{self.config.io_base_path}/io/write?fileId={file_id}"
                    f"&sizeKb={size_kib}"
                    f"&segments={self.config.io_segments}"
                    f"&holdMs={self.config.io_hold_ms}"
                ),
                report_url=f"{self.config.io_base_path}/io/write",
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
