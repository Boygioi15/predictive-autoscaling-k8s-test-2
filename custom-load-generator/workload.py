from __future__ import annotations

import os
from dataclasses import dataclass


DEFAULT_REQUEST_CLASSES = (
    "directory",
    "image",
    "html",
    "other",
    "audio",
    "java",
    "video",
    "compressed",
    "dynamic",
)

REQUEST_CLASS_COLUMNS = {
    "html": "type_HTML",
    "image": "type_IMAGE",
    "audio": "type_AUDIO",
    "video": "type_VIDEO",
    "java": "type_JAVA",
    "dynamic": "type_DYNAMIC",
    "compressed": "type_COMPRESSED",
    "directory": "type_DIRECTORY",
    "other": "type_OTHER",
}


@dataclass(frozen=True)
class PreparedRequest:
    method: str
    path: str
    report_url: str
    json_body: dict[str, object] | None = None


@dataclass(frozen=True)
class WorkloadConfig:
    seed: int
    demand_base_path: str
    request_classes: tuple[str, ...]


def _get_int(env_name: str, default: int) -> int:
    raw_value = os.getenv(env_name, str(default))
    try:
        return int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{env_name} must be an integer, got: {raw_value!r}") from exc


def _normalize_base_path(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError("DEMAND_BASE_PATH must not be empty")
    if not stripped.startswith("/"):
        stripped = f"/{stripped}"
    return stripped.rstrip("/")


def _parse_request_classes(value: str | None) -> tuple[str, ...]:
    if value is None:
        return DEFAULT_REQUEST_CLASSES

    parsed = tuple(segment.strip().lower() for segment in value.split(",") if segment.strip())
    if not parsed:
        raise ValueError("REQUEST_CLASSES must include at least one request class")

    duplicates = sorted({request_class for request_class in parsed if parsed.count(request_class) > 1})
    if duplicates:
        raise ValueError(f"REQUEST_CLASSES must not contain duplicates, got: {duplicates}")

    unknown = sorted(request_class for request_class in parsed if request_class not in REQUEST_CLASS_COLUMNS)
    if unknown:
        raise ValueError(f"REQUEST_CLASSES contains unsupported request classes: {unknown}")

    return parsed


def load_workload_config() -> WorkloadConfig:
    return WorkloadConfig(
        seed=_get_int("SCRIPT_RANDOM_SEED", 42),
        demand_base_path=_normalize_base_path(os.getenv("DEMAND_BASE_PATH", "/demand")),
        request_classes=_parse_request_classes(os.getenv("REQUEST_CLASSES")),
    )


class WorkloadPlanner:
    def __init__(self, config: WorkloadConfig):
        self.config = config
        if not self.config.request_classes:
            raise ValueError("At least one request class must be configured")

    def operation_names(self) -> list[str]:
        return list(self.config.request_classes)

    def request_class_for_index(
        self, request_class_counts: tuple[int, ...], request_index_within_second: int
    ) -> str:
        running_total = 0
        for request_class, request_count in zip(self.config.request_classes, request_class_counts):
            running_total += request_count
            if request_index_within_second < running_total:
                return request_class

        raise IndexError(
            f"request_index_within_second {request_index_within_second} is outside the request class counts"
        )

    def build_request(self, request_class: str) -> PreparedRequest:
        path = f"{self.config.demand_base_path}/{request_class}"
        return PreparedRequest(method="GET", path=path, report_url=path)
