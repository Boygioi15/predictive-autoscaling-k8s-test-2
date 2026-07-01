from __future__ import annotations

from bisect import bisect_right
from datetime import UTC, datetime, timedelta
from pathlib import Path
import threading
from typing import Any


class ScriptRangeStore:
    def __init__(
        self,
        csv_path: Path,
        *,
        index_stride: int = 10_000,
        max_points: int = 600,
    ) -> None:
        self._csv_path = csv_path
        self._index_stride = max(index_stride, 1)
        self._max_points = max(max_points, 32)
        self._index_lock = threading.Lock()
        self._index_ready = False
        self._header_offset = 0
        self._index: list[tuple[datetime, int]] = []
        self._index_timestamps: list[datetime] = []
        self._first_timestamp: datetime | None = None
        self._last_timestamp: datetime | None = None

    def get_range(
        self,
        *,
        real_start: datetime | None = None,
        world_cup_start: datetime | None = None,
        duration_seconds: int | None = None,
    ) -> dict[str, Any]:
        if not self._csv_path.exists():
            return {
                "available": False,
                "message": f"CSV file was not found at {self._csv_path}",
            }

        self._ensure_index()
        if self._first_timestamp is None or self._last_timestamp is None:
            return {
                "available": False,
                "message": "CSV file did not contain any readable rows.",
            }

        resolved_world_cup_start = world_cup_start or self._first_timestamp
        resolved_real_start = (real_start or datetime.now(UTC)).astimezone(UTC).replace(second=0, microsecond=0)
        resolved_duration = max(int(duration_seconds or 3600), 1)

        if resolved_world_cup_start < self._first_timestamp:
            resolved_world_cup_start = self._first_timestamp
        if resolved_world_cup_start > self._last_timestamp:
            resolved_world_cup_start = self._last_timestamp

        points = self._slice_filled_series(
            world_cup_start=resolved_world_cup_start,
            real_start=resolved_real_start,
            duration_seconds=resolved_duration,
        )
        sampled_points = self._downsample_points(points, max_points=self._max_points)

        request_values = [point["requests"] for point in points]

        return {
            "available": True,
            "csvPath": str(self._csv_path),
            "query": {
                "realStart": resolved_real_start.isoformat(),
                "worldCupStart": resolved_world_cup_start.isoformat(),
                "durationSeconds": resolved_duration,
            },
            "file": {
                "worldCupStart": self._first_timestamp.isoformat(),
                "worldCupEnd": self._last_timestamp.isoformat(),
            },
            "summary": {
                "totalPoints": len(points),
                "sampledPoints": len(sampled_points),
                "totalRequests": sum(request_values),
                "peakRequestsPerSecond": max(request_values) if request_values else 0,
            },
            "series": sampled_points,
        }

    def _ensure_index(self) -> None:
        if self._index_ready:
            return

        with self._index_lock:
            if self._index_ready:
                return

            self._index = []
            self._index_timestamps = []
            row_index = 0

            with self._csv_path.open("rb") as handle:
                handle.readline()
                self._header_offset = handle.tell()
                current_offset = self._header_offset

                while True:
                    line = handle.readline()
                    if not line:
                        break

                    parsed = self._parse_line(line)
                    if parsed is not None:
                        timestamp, _requests = parsed
                        if self._first_timestamp is None:
                            self._first_timestamp = timestamp
                        self._last_timestamp = timestamp
                        if row_index % self._index_stride == 0:
                            self._index.append((timestamp, current_offset))
                            self._index_timestamps.append(timestamp)

                    current_offset = handle.tell()
                    row_index += 1

            self._index_ready = True

    def _slice_filled_series(
        self,
        *,
        world_cup_start: datetime,
        real_start: datetime,
        duration_seconds: int,
    ) -> list[dict[str, Any]]:
        points_by_offset: dict[int, int] = {}
        world_cup_end = world_cup_start + timedelta(seconds=duration_seconds)
        read_offset = self._starting_offset(world_cup_start)

        with self._csv_path.open("rb") as handle:
            handle.seek(read_offset)
            while True:
                line = handle.readline()
                if not line:
                    break

                parsed = self._parse_line(line)
                if parsed is None:
                    continue

                timestamp, requests = parsed
                if timestamp < world_cup_start:
                    continue
                if timestamp >= world_cup_end:
                    break

                second_offset = int((timestamp - world_cup_start).total_seconds())
                if 0 <= second_offset < duration_seconds:
                    points_by_offset[second_offset] = requests

        points: list[dict[str, Any]] = []
        for second_offset in range(duration_seconds):
            world_cup_time = world_cup_start + timedelta(seconds=second_offset)
            real_time = real_start + timedelta(seconds=second_offset)
            points.append(
                {
                    "worldCupTime": world_cup_time.isoformat(),
                    "realTime": real_time.isoformat(),
                    "requests": points_by_offset.get(second_offset, 0),
                }
            )
        return points

    def _starting_offset(self, world_cup_start: datetime) -> int:
        if not self._index:
            return self._header_offset

        index_position = bisect_right(self._index_timestamps, world_cup_start) - 1
        if index_position < 0:
            return self._header_offset
        return self._index[index_position][1]

    def _downsample_points(
        self,
        points: list[dict[str, Any]],
        *,
        max_points: int,
    ) -> list[dict[str, Any]]:
        if len(points) <= max_points:
            return points

        result: list[dict[str, Any]] = []
        total_points = len(points)
        for point_index in range(max_points):
            start_index = round((point_index / max_points) * total_points)
            end_index = round(((point_index + 1) / max_points) * total_points)
            bucket = points[start_index:max(end_index, start_index + 1)]
            avg_requests = sum(item["requests"] for item in bucket) / len(bucket)
            midpoint = bucket[len(bucket) // 2]
            result.append(
                {
                    "worldCupTime": midpoint["worldCupTime"],
                    "realTime": midpoint["realTime"],
                    "requests": round(avg_requests, 2),
                }
            )
        return result

    def _parse_line(self, line: bytes) -> tuple[datetime, int] | None:
        decoded = line.decode("utf-8", errors="ignore").strip()
        if not decoded:
            return None

        parts = decoded.split(",", 4)
        if len(parts) < 3:
            return None

        try:
            timestamp = datetime.fromisoformat(parts[1]).astimezone(UTC)
            requests = int(float(parts[2]))
        except ValueError:
            return None

        return timestamp, requests
