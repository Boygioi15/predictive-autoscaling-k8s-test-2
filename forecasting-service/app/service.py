import math
import logging
from typing import Any

import httpx

from .clients import AIServerClient, PrometheusClient
from .config import settings
from .models import PredictionRequest, PredictionResponse


logger = logging.getLogger(__name__)


class ForecastingService:
    def __init__(self) -> None:
        self.prometheus = PrometheusClient()
        self.ai_server = AIServerClient()

    async def predict_workload(self, request: PredictionRequest) -> PredictionResponse:
        query = request.prometheus_query or settings.prometheus_query
        logger.info(
            "Starting workload prediction for deployment=%s metric=%s query=%s",
            request.deployment_name,
            request.target_metric_name,
            query,
        )

        prometheus_value = await self.prometheus.query_instant(query)
        logger.info(
            "Fetched Prometheus value deployment=%s metric=%s value=%s",
            request.deployment_name,
            request.target_metric_name,
            prometheus_value,
        )
    
        ai_server_used = False
        raw_ai_response: dict[str, Any] | None = None
        predicted_value = prometheus_value

        try:
            logger.info(
                "Calling AI server for deployment=%s metric=%s",
                request.deployment_name,
                request.target_metric_name,
            )
            raw_ai_response = await self.ai_server.predict(
                prometheus_value=prometheus_value,
                metric_name=request.target_metric_name,
                deployment_name=request.deployment_name,
            )
            predicted_value = self._extract_prediction(raw_ai_response, prometheus_value)
            ai_server_used = True
            logger.info(
                "AI server prediction received deployment=%s predicted_value=%s",
                request.deployment_name,
                predicted_value,
            )
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            logger.exception(
                "AI server prediction failed for deployment=%s, using fallback=%s",
                request.deployment_name,
                settings.fallback_prediction_enabled,
            )
            if not settings.fallback_prediction_enabled:
                raise

        recommended_replicas = self._calculate_replicas(predicted_value)
        logger.info(
            "Prediction complete deployment=%s predicted_value=%s recommended_replicas=%s ai_server_used=%s",
            request.deployment_name,
            predicted_value,
            recommended_replicas,
            ai_server_used,
        )

        return PredictionResponse(
            workload_prediction=predicted_value,
            recommended_replicas=recommended_replicas,
            replica=recommended_replicas,
            metric_name=request.target_metric_name,
            query_used=query,
            prometheus_value=prometheus_value,
            ai_server_used=ai_server_used,
            deployment_name=request.deployment_name,
            raw_ai_response=raw_ai_response,
        )

    def _extract_prediction(self, payload: dict[str, Any], fallback: float) -> float:
        for key in ("predicted_workload", "prediction", "value", "forecast"):
            value = payload.get(key)
            if value is not None:
                return float(value)
        raise ValueError(f"AI server response missing prediction field: {payload}")

    def _calculate_replicas(self, predicted_value: float) -> int:
        desired = math.ceil(predicted_value / settings.replica_divisor)
        desired = max(settings.min_replicas, desired)
        return min(settings.max_replicas, desired)
