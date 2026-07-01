from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

import httpx

from .settings import settings


@dataclass(frozen=True)
class PrometheusPoint:
    timestamp: str
    value: float


@dataclass(frozen=True)
class PrometheusSeries:
    name: str
    points: list[PrometheusPoint]


class PrometheusClient:
    def __init__(self) -> None:
        self._base_url = settings.prometheus_base_url.rstrip("/")
        self._timeout = settings.prometheus_timeout_seconds

    async def query_range(
        self,
        query: str,
        *,
        start: datetime,
        end: datetime,
        step_seconds: int,
    ) -> list[PrometheusSeries]:
        params = {
            "query": query,
            "start": start.timestamp(),
            "end": end.timestamp(),
            "step": f"{step_seconds}s",
        }

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(
                f"{self._base_url}/api/v1/query_range",
                params=params,
            )
            response.raise_for_status()
            payload = response.json()

        if payload.get("status") != "success":
            raise ValueError(f"Prometheus query_range failed with payload status={payload.get('status')!r}")

        result = payload.get("data", {}).get("result", [])
        series_list: list[PrometheusSeries] = []
        for item in result:
            metric = item.get("metric", {})
            points: list[PrometheusPoint] = []
            for timestamp, value in item.get("values", []):
                parsed_value = float(value)
                if not math.isfinite(parsed_value):
                    continue
                points.append(
                    PrometheusPoint(
                        timestamp=datetime.fromtimestamp(float(timestamp)).isoformat(),
                        value=parsed_value,
                    )
                )

            series_list.append(
                PrometheusSeries(
                    name=self._series_name(metric),
                    points=points,
                )
            )

        return series_list

    def _series_name(self, metric: dict[str, str]) -> str:
        for key in ("state", "pod", "route", "method", "job", "__name__"):
            value = metric.get(key)
            if value:
                return value
        return "value"
