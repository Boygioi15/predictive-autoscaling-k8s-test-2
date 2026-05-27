from typing import Any

import httpx

from .config import settings
from .models import PrometheusQueryResponse


class PrometheusClient:
    async def query_instant(self, query: str) -> float:
        async with httpx.AsyncClient(timeout=settings.prometheus_timeout_seconds) as client:
            response = await client.get(
                f"{settings.prometheus_base_url.rstrip('/')}/api/v1/query",
                params={"query": query},
            )
            print("Prome response: ",response)
            response.raise_for_status()
            payload = PrometheusQueryResponse.model_validate(response.json())

        if payload.status != "success":
            raise ValueError(f"Prometheus query failed with status={payload.status}")

        if not payload.data.result:
            return 0.0

        sample_value = payload.data.result[0].value
        if len(sample_value) < 2:
            raise ValueError("Prometheus response did not include a numeric sample value")

        return float(sample_value[1])


class AIServerClient:
    async def predict(self, prometheus_value: float, metric_name: str, deployment_name: str | None) -> dict[str, Any]:
        body = {
            "metric_name": metric_name,
            "current_value": prometheus_value,
            "deployment_name": deployment_name,
        }

        async with httpx.AsyncClient(timeout=settings.ai_server_timeout_seconds) as client:
            response = await client.post(settings.ai_server_url, json=body)
            response.raise_for_status()
            return response.json()
