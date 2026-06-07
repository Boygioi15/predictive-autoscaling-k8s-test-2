from datetime import datetime
from typing import Any

import httpx

from .config import settings
from .models import PrometheusQueryRangeResponse, RemotePredictionRequest


class PrometheusClient:
    async def query_range(
        self,
        query: str,
        *,
        start: datetime,
        end: datetime,
        step_seconds: int,
        expected_points: int,
    ) -> list[float]:
        params = {
            "query": query,
            "start": start.timestamp(),
            "end": end.timestamp(),
            "step": f"{step_seconds}s",
        }

        async with httpx.AsyncClient(timeout=settings.prometheus_timeout_seconds) as client:
            response = await client.get(
                f"{settings.prometheus_base_url.rstrip('/')}/api/v1/query_range",
                params=params,
            )
            response.raise_for_status()
            payload = PrometheusQueryRangeResponse.model_validate(response.json())

        if payload.status != "success":
            raise ValueError(f"Prometheus range query failed with status={payload.status}")

        if not payload.data.result:
            return [0.0] * expected_points

        sample = payload.data.result[0]
        points_by_timestamp = {
            int(float(timestamp)): float(value)
            for timestamp, value in sample.values
            if len((timestamp, value)) == 2
        }

        start_ts = int(start.timestamp())
        return [
            points_by_timestamp.get(start_ts + index * step_seconds, 0.0)
            for index in range(expected_points)
        ]


class RemoteModelClient:
    async def predict(
        self,
        *,
        endpoint: str,
        payload: RemotePredictionRequest,
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=settings.remote_model_timeout_seconds) as client:
            response = await client.post(endpoint, json=payload.model_dump(mode="json"))
            response.raise_for_status()
            return response.json()
