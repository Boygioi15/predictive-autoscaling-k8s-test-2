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
    distribution_mode: str
    prime_user_weight: int
    memory_user_weight: int
    io_user_weight: int
    prime_range_weight: int
    prime_kth_weight: int
    prime_check_weight: int
    text_pressure_weight: int
    io_read_weight: int
    io_write_weight: int
    prime_range_value: int
    prime_kth_value: int
    prime_check_value: int
    prime_range_min: int
    prime_range_max: int
    prime_range_mean: int
    prime_range_standard: int
    prime_kth_min: int
    prime_kth_max: int
    prime_kth_mean: int
    prime_kth_standard: int
    prime_check_min: int
    prime_check_max: int
    prime_check_mean: int
    prime_check_standard: int
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


def _get_first_int(env_names: tuple[str, ...], default: int) -> int:
    for env_name in env_names:
        raw_value = os.getenv(env_name)
        if raw_value is None:
            continue
        try:
            return int(raw_value)
        except ValueError as exc:
            raise ValueError(f"{env_name} must be an integer, got: {raw_value!r}") from exc
    return default


def _get_first_int_range(
    min_env_names: tuple[str, ...],
    max_env_names: tuple[str, ...],
    default_min: int,
    default_max: int,
) -> tuple[int, int]:
    min_value = _get_first_int(min_env_names, default_min)
    max_value = _get_first_int(max_env_names, default_max)
    if min_value <= max_value:
        return min_value, max_value
    return max_value, min_value


def _get_distribution_mode() -> str:
    raw_value = os.getenv("DISTRIBUTION_MODE", "UNIFORM").strip().upper()
    if raw_value == "DISTRIBUTION":
        return "NORMAL"
    if raw_value in {"EQUAL", "UNIFORM", "NORMAL"}:
        return raw_value
    raise ValueError("DISTRIBUTION_MODE must be one of EQUAL, UNIFORM, NORMAL")


def _validate_bounded_normal(name: str, min_value: int, max_value: int, mean: int, standard_deviation: int) -> None:
    if mean < min_value or mean > max_value:
        raise ValueError(f"{name}_MEAN must be within [{name}_MIN, {name}_MAX]")
    if standard_deviation < 0:
        raise ValueError(f"{name}_STANDARD must be greater than or equal to 0")


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
    distribution_mode = _get_distribution_mode()
    prime_range_min, prime_range_max = _get_int_range("PRIME_RANGE_MIN", "PRIME_RANGE_MAX", 1_000, 500_000)
    prime_kth_min, prime_kth_max = _get_int_range("PRIME_KTH_MIN", "PRIME_KTH_MAX", 1_000, 50_000)
    prime_check_min, prime_check_max = _get_int_range("PRIME_CHECK_MIN", "PRIME_CHECK_MAX", 5_000_000, 100_000_000)
    io_read_min_kib, io_read_max_kib = _get_int_range("IO_READ_MIN_KIB", "IO_READ_MAX_KIB", 128, 1024)
    io_write_min_kib, io_write_max_kib = _get_int_range("IO_WRITE_MIN_KIB", "IO_WRITE_MAX_KIB", 128, 1024)
    prime_range_mean = _get_int("PRIME_RANGE_MEAN", (prime_range_min + prime_range_max) // 2)
    prime_range_standard = max(0, _get_int("PRIME_RANGE_STANDARD", 0))
    prime_kth_mean = _get_int("PRIME_KTH_MEAN", (prime_kth_min + prime_kth_max) // 2)
    prime_kth_standard = max(0, _get_int("PRIME_KTH_STANDARD", 0))
    prime_check_mean = _get_int("PRIME_CHECK_MEAN", (prime_check_min + prime_check_max) // 2)
    prime_check_standard = max(0, _get_int("PRIME_CHECK_STANDARD", 0))

    if distribution_mode == "NORMAL":
        _validate_bounded_normal(
            "PRIME_RANGE",
            prime_range_min,
            prime_range_max,
            prime_range_mean,
            prime_range_standard,
        )
        _validate_bounded_normal(
            "PRIME_KTH",
            prime_kth_min,
            prime_kth_max,
            prime_kth_mean,
            prime_kth_standard,
        )
        _validate_bounded_normal(
            "PRIME_CHECK",
            prime_check_min,
            prime_check_max,
            prime_check_mean,
            prime_check_standard,
        )

    return WorkloadConfig(
        seed=_get_int("SCRIPT_RANDOM_SEED", 42),
        distribution_mode=distribution_mode,
        prime_user_weight=max(0, _get_int("PRIME_USER_WEIGHT", 1)),
        memory_user_weight=_get_weight("MEMORY_USER_WEIGHT", "TEXT_USER_WEIGHT", 2),
        io_user_weight=max(0, _get_int("IO_USER_WEIGHT", 0)),
        prime_range_weight=_get_weight("PRIME_RANGE_WEIGHT", "PRIME_USER_WEIGHT", 1),
        prime_kth_weight=_get_weight("PRIME_KTH_WEIGHT", "PRIME_USER_WEIGHT", 1),
        prime_check_weight=_get_weight("PRIME_CHECK_WEIGHT", "PRIME_USER_WEIGHT", 1),
        text_pressure_weight=_get_weight("TEXT_PRESSURE_WEIGHT", "MEMORY_USER_WEIGHT", 2),
        io_read_weight=_get_weight("IO_READ_WEIGHT", "IO_USER_WEIGHT", 0),
        io_write_weight=_get_weight("IO_WRITE_WEIGHT", "IO_USER_WEIGHT", 0),
        prime_range_value=_get_first_int(("PRIME_RANGE", "PRIME_RANGE_"), 400_000),
        prime_kth_value=_get_first_int(("PRIME_KTH",), 35_000),
        prime_check_value=_get_first_int(("PRIME_CHECK",), 100_000_000),
        prime_range_min=prime_range_min,
        prime_range_max=prime_range_max,
        prime_range_mean=prime_range_mean,
        prime_range_standard=prime_range_standard,
        prime_kth_min=prime_kth_min,
        prime_kth_max=prime_kth_max,
        prime_kth_mean=prime_kth_mean,
        prime_kth_standard=prime_kth_standard,
        prime_check_min=prime_check_min,
        prime_check_max=prime_check_max,
        prime_check_mean=prime_check_mean,
        prime_check_standard=prime_check_standard,
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
        operations: list[OperationDefinition] = []

        if self.config.prime_user_weight > 0:
            if self.config.prime_range_weight > 0:
                operations.append(OperationDefinition("prime-range", self.config.prime_range_weight))
            if self.config.prime_kth_weight > 0:
                operations.append(OperationDefinition("prime-kth", self.config.prime_kth_weight))
            if self.config.prime_check_weight > 0:
                operations.append(OperationDefinition("prime-check", self.config.prime_check_weight))

        if self.config.memory_user_weight > 0 and self.config.text_pressure_weight > 0:
            operations.append(OperationDefinition("text-pressure", self.config.text_pressure_weight))

        if self.config.io_user_weight > 0:
            if self.config.io_read_weight > 0:
                operations.append(OperationDefinition("io-read", self.config.io_read_weight))
            if self.config.io_write_weight > 0:
                operations.append(OperationDefinition("io-write", self.config.io_write_weight))

        if not operations:
            raise ValueError(
                "At least one endpoint weight must be greater than 0. "
                "Check PRIME_*_WEIGHT, TEXT_PRESSURE_WEIGHT, and IO_*_WEIGHT."
            )

        cycle: list[OperationDefinition] = []
        for operation in operations:
            cycle.extend([operation] * operation.weight)

        random.Random(self.config.seed).shuffle(cycle)
        return cycle

    def operation_names(self) -> list[str]:
        return sorted({operation.name for operation in self._cycle})

    def _sample_prime_value(
        self,
        rng: random.Random,
        *,
        exact_value: int,
        min_value: int,
        max_value: int,
        mean: int,
        standard_deviation: int,
    ) -> int:
        if self.config.distribution_mode == "EQUAL":
            return exact_value

        if self.config.distribution_mode == "NORMAL":
            return _sample_bounded_normal_int(
                rng,
                min_value=min_value,
                max_value=max_value,
                mean=mean,
                standard_deviation=standard_deviation,
            )

        return rng.randint(min_value, max_value)

    def build_request(
        self,
        scheduled_index: int,
        second_index: int,
        request_index_within_second: int,
    ) -> PreparedRequest:
        operation = self._cycle[scheduled_index % len(self._cycle)]
        rng = random.Random(self._request_seed(operation.name, second_index, request_index_within_second, scheduled_index))

        if operation.name == "prime-range":
            n = self._sample_prime_value(
                rng,
                exact_value=self.config.prime_range_value,
                min_value=self.config.prime_range_min,
                max_value=self.config.prime_range_max,
                mean=self.config.prime_range_mean,
                standard_deviation=self.config.prime_range_standard,
            )
            return PreparedRequest(
                method="GET",
                path=f"{self.config.prime_base_path}/range?n={n}",
                report_url=f"{self.config.prime_base_path}/range",
            )

        if operation.name == "prime-kth":
            k = self._sample_prime_value(
                rng,
                exact_value=self.config.prime_kth_value,
                min_value=self.config.prime_kth_min,
                max_value=self.config.prime_kth_max,
                mean=self.config.prime_kth_mean,
                standard_deviation=self.config.prime_kth_standard,
            )
            return PreparedRequest(
                method="GET",
                path=f"{self.config.prime_base_path}/kth?k={k}",
                report_url=f"{self.config.prime_base_path}/kth",
            )

        if operation.name == "prime-check":
            n = self._sample_prime_value(
                rng,
                exact_value=self.config.prime_check_value,
                min_value=self.config.prime_check_min,
                max_value=self.config.prime_check_max,
                mean=self.config.prime_check_mean,
                standard_deviation=self.config.prime_check_standard,
            )
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


def _sample_bounded_normal_int(
    rng: random.Random,
    *,
    min_value: int,
    max_value: int,
    mean: int,
    standard_deviation: int,
    attempts: int = 32,
) -> int:
    if standard_deviation <= 0:
        return max(min_value, min(max_value, int(round(mean))))

    for _ in range(attempts):
        sampled = int(round(rng.gauss(mean, standard_deviation)))
        if min_value <= sampled <= max_value:
            return sampled

    sampled = int(round(rng.gauss(mean, standard_deviation)))
    return max(min_value, min(max_value, sampled))


def _random_text(rng: random.Random, size: int) -> str:
    word_count = max(1, size // 5)
    words = []
    for _ in range(word_count):
        word = "".join(rng.choice(string.ascii_lowercase) for _ in range(5))
        words.append(word)
    return " ".join(words)
