import math
import json
import logging
from datetime import datetime
from typing import Any

import httpx
from pydantic import BaseModel

from .config import settings
from .models import PrometheusQueryRangeResponse

logger = logging.getLogger("uvicorn.error")


def _format_prometheus_duration(seconds: float) -> str:
    whole_seconds = int(seconds)
    if math.isclose(seconds, whole_seconds):
        return f"{whole_seconds}s"

    milliseconds = max(1, math.ceil(seconds * 1000))
    return f"{milliseconds}ms"


class PrometheusClient:
    async def query_range(
        self,
        query: str,
        *,
        start: datetime,
        end: datetime,
        step_seconds: int,
        expected_points: int,
        nullable: bool = False,
    ) -> list[float | None]:
        params = {
            "query": query,
            "start": start.timestamp(),
            "end": end.timestamp(),
            "step": f"{step_seconds}s",
            "timeout": _format_prometheus_duration(settings.prometheus_timeout_seconds),
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
            if nullable:
                return [None] * expected_points
            return [0.0] * expected_points

        sample = payload.data.result[0]
        points_by_timestamp: dict[int, float | None] = {}
        for timestamp, value in sample.values:
            parsed_value = float(value)
            if not math.isfinite(parsed_value):
                if nullable:
                    points_by_timestamp[int(float(timestamp))] = None
                    continue
                parsed_value = 0.0
            points_by_timestamp[int(float(timestamp))] = parsed_value

        start_ts = int(start.timestamp())
        return [
            points_by_timestamp.get(start_ts + index * step_seconds, None if nullable else 0.0)
            for index in range(expected_points)
        ]


class RemoteModelClient:
    async def predict(
        self,
        *,
        endpoint: str,
        payload: BaseModel | dict[str, Any],
    ) -> dict[str, Any]:
        json_payload = (
            payload.model_dump(mode="json")
            if isinstance(payload, BaseModel)
            else payload
        )
        pretty_payload = json.dumps(
            json_payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        logger.info(
            "Sending remote model request endpoint=%s payload=\n%s",
            endpoint,
            pretty_payload,
        )
        async with httpx.AsyncClient(timeout=settings.remote_model_timeout_seconds) as client:
            response = await client.post(
                endpoint,
                json=json_payload,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            )
            response.raise_for_status()
            response_payload = response.json()
            logger.info(
                "Received remote model response endpoint=%s status=%s payload=\n%s",
                endpoint,
                response.status_code,
                json.dumps(response_payload, ensure_ascii=False, indent=2, sort_keys=True),
            )
            return response_payload
