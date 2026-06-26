import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .clients import PrometheusClient, RemoteModelClient
from .config import settings
from .models import (
    ForecastOption,
    ForecastRequest,
    ForecastResponse,
    LinearRegressionServingRequest,
    LinearRegressionServingResponse,
    MetricForecastRow,
    RemotePredictionRequest,
)


logger = logging.getLogger("uvicorn.error")

LINEAR_REGRESSION_HISTORY_METRICS = (
    "total_requests_per_minute",
    "total_cpu_seconds_per_minute",
    "total_bandwidth_bytes_per_minute",
)


@dataclass
class PredictionResult:
    predictions: list[float]
    prediction_rows: list[MetricForecastRow] = field(default_factory=list)
    current_time_origin: datetime | None = None
    world_cup_time_origin: datetime | None = None
    remote_endpoint: str | None = None
    remote_contract: str | None = None
    required_history_rows: int | None = None
    provided_history_rows: int | None = None
    buffered_history_rows: int | None = None


class ForecastingService:
    def __init__(self) -> None:
        self.prometheus = PrometheusClient()
        self.remote_model = RemoteModelClient()

    async def predict_workload(self, request: ForecastRequest) -> ForecastResponse:
        contract_id = request.contract_id
        options = self._load_options()
        if contract_id not in options:
            raise KeyError(
                f"Contract '{contract_id}' was not found in {settings.forecast_options_path}"
            )

        option = options[contract_id]
        deployment = option.deployment
        generated_at = self._aligned_now(option.step_seconds)

        logger.info(
            "Starting forecast contract_id=%s deployment=%s model=%s generated_at=%s namespace=%s service=%s ingress=%s",
            contract_id,
            deployment,
            option.model_full_name,
            generated_at.isoformat(),
            option.namespace,
            option.service,
            option.ingress,
        )

        history = await self._fetch_feature_history(
            option=option,
            generated_at=generated_at,
        )

        observed = await self._fetch_guardrail_history(
            option=option,
            generated_at=generated_at,
        )

        prediction_result = await self._predict(
            option=option,
            history=history,
            generated_at=generated_at,
        )

        return ForecastResponse(
            deployment=deployment,
            contract_id=contract_id,
            target_metric=option.target_metric,
            feature_metrics=option.feature_metrics,
            step_seconds=option.step_seconds,
            predictions=prediction_result.predictions,
            observed=observed,
            model_name=option.model_name,
            model_version=option.model_version,
            generated_at=generated_at,
            prediction_rows=prediction_result.prediction_rows,
            current_time_origin=prediction_result.current_time_origin,
            world_cup_time_origin=prediction_result.world_cup_time_origin,
            remote_endpoint=prediction_result.remote_endpoint,
            remote_contract=prediction_result.remote_contract,
            required_history_rows=prediction_result.required_history_rows,
            provided_history_rows=prediction_result.provided_history_rows,
            buffered_history_rows=prediction_result.buffered_history_rows,
        )

    def _load_options(self) -> dict[str, ForecastOption]:
        payload = self._load_json_file(settings.forecast_options_path)
        options: dict[str, ForecastOption] = {}

        for contract_id, option_payload in payload.items():
            options[contract_id] = ForecastOption.model_validate(option_payload)

        if not options:
            raise ValueError("No forecast options were loaded")

        return options

    def _load_json_file(self, path_value: str) -> dict[str, Any]:
        path = Path(path_value)
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    async def _fetch_feature_history(
        self,
        *,
        option: ForecastOption,
        generated_at: datetime,
    ) -> dict[str, list[float]]:
        start = generated_at - timedelta(
            seconds=option.step_seconds * (option.lookback_steps - 1)
        )
        history: dict[str, list[float]] = {}

        for metric_name in option.feature_metrics:
            raw_query = option.query_for_metric(metric_name)
            query = self._render_query(raw_query, option)
            values = await self.prometheus.query_range(
                query,
                start=start,
                end=generated_at,
                step_seconds=option.step_seconds,
                expected_points=option.lookback_steps,
            )
            history[metric_name] = [float(value) for value in values]
            logger.info(
                "Fetched Prometheus history contract_deployment=%s metric=%s points=%s",
                option.deployment,
                metric_name,
                len(values),
            )

        return history

    async def _fetch_guardrail_history(
        self,
        *,
        option: ForecastOption,
        generated_at: datetime,
    ) -> dict[str, list[float | None]]:
        if not option.guardrail_queries:
            return {}

        start = generated_at - timedelta(
            seconds=option.step_seconds * (option.horizon_steps - 1)
        )
        observed: dict[str, list[float | None]] = {}

        for metric_name, raw_query in option.guardrail_queries.items():
            query = self._render_query(raw_query, option)
            values = await self.prometheus.query_range(
                query,
                start=start,
                end=generated_at,
                step_seconds=option.step_seconds,
                expected_points=option.horizon_steps,
                nullable=True,
            )
            observed[metric_name] = values
            logger.info(
                "Fetched Prometheus guardrail history contract_deployment=%s metric=%s points=%s",
                option.deployment,
                metric_name,
                len(values),
            )

        return observed

    def _render_query(
        self,
        query: str,
        option: ForecastOption,
    ) -> str:
        replacements = {
            "deployment": option.deployment,
            "namespace": option.namespace,
            "service": option.service,
            "ingress": option.ingress,
            "app_pod_regex": option.app_pod_regex,
        }

        rendered = query
        for key, value in replacements.items():
            rendered = rendered.replace(f"{{{{{key}}}}}", value)
        return rendered

    async def _predict(
        self,
        *,
        option: ForecastOption,
        history: dict[str, list[float]],
        generated_at: datetime,
    ) -> PredictionResult:
        if option.local:
            return self._predict_local(option=option, history=history, generated_at=generated_at)

        if option.remote_contract == "linear_regression_serving_v1":
            return await self._predict_linear_regression(
                option=option,
                history=history,
                generated_at=generated_at,
            )

        return await self._predict_legacy_remote(
            option=option,
            history=history,
            generated_at=generated_at,
        )

    def _predict_local(
        self,
        *,
        option: ForecastOption,
        history: dict[str, list[float]],
        generated_at: datetime,
    ) -> PredictionResult:
        model_name = option.model_name

        if model_name == "last_value":
            primary_metric = option.remote_target_metric or option.feature_metrics[0]
            series = history.get(primary_metric, [])
            last_value = series[-1] if series else 0.0
            prediction_rows = self._build_last_value_prediction_rows(
                history=history,
                generated_at=generated_at,
                step_seconds=option.step_seconds,
                horizon_steps=option.horizon_steps,
            )
            return PredictionResult(
                predictions=[last_value] * option.horizon_steps,
                prediction_rows=prediction_rows,
                current_time_origin=generated_at,
            )

        raise ValueError(
            f"Unsupported local model '{option.model_full_name}'. "
            "Only last_value is implemented locally right now."
        )

    def _build_last_value_prediction_rows(
        self,
        *,
        history: dict[str, list[float]],
        generated_at: datetime,
        step_seconds: int,
        horizon_steps: int,
    ) -> list[MetricForecastRow]:
        if not all(metric_name in history for metric_name in LINEAR_REGRESSION_HISTORY_METRICS):
            return []

        latest_values = {
            metric_name: float(history[metric_name][-1]) if history[metric_name] else 0.0
            for metric_name in LINEAR_REGRESSION_HISTORY_METRICS
        }

        rows: list[MetricForecastRow] = []
        for step in range(1, horizon_steps + 1):
            rows.append(
                MetricForecastRow(
                    datetime=generated_at + timedelta(seconds=step * step_seconds),
                    total_requests_per_minute=latest_values["total_requests_per_minute"],
                    total_cpu_seconds_per_minute=latest_values["total_cpu_seconds_per_minute"],
                    total_bandwidth_bytes_per_minute=latest_values["total_bandwidth_bytes_per_minute"],
                )
            )

        return rows

    async def _predict_legacy_remote(
        self,
        *,
        option: ForecastOption,
        history: dict[str, list[float]],
        generated_at: datetime,
    ) -> PredictionResult:
        payload = RemotePredictionRequest(
            deployment=option.deployment,
            target_metric=option.target_metric,
            feature_metrics=option.feature_metrics,
            lookback_steps=option.lookback_steps,
            horizon_steps=option.horizon_steps,
            step_seconds=option.step_seconds,
            model_full_name=option.model_full_name,
            generated_at=generated_at,
            history=history,
        )
        raw_response = await self.remote_model.predict(
            endpoint=option.endpoint or "",
            payload=payload,
        )
        predictions = self._extract_predictions(raw_response, option.horizon_steps)
        logger.info(
            "Remote forecast complete model=%s horizon=%s contract=%s",
            option.model_full_name,
            len(predictions),
            option.remote_contract,
        )
        return PredictionResult(
            predictions=predictions,
            current_time_origin=generated_at,
            remote_endpoint=option.endpoint,
            remote_contract=option.remote_contract,
        )

    async def _predict_linear_regression(
        self,
        *,
        option: ForecastOption,
        history: dict[str, list[float]],
        generated_at: datetime,
    ) -> PredictionResult:
        history_rows = self._build_linear_regression_history_rows(
            history=history,
            generated_at=generated_at,
            step_seconds=option.step_seconds,
            required_rows=option.lookback_steps,
        )
        payload = LinearRegressionServingRequest(
            current_time_origin=generated_at,
            history=history_rows,
        )
        raw_response = await self.remote_model.predict(
            endpoint=option.endpoint or "",
            payload=payload,
        )
        response = LinearRegressionServingResponse.model_validate(raw_response)
        remote_target_metric = option.remote_target_metric or option.target_metric
        predictions = self._extract_metric_predictions(
            response=response,
            metric_name=remote_target_metric,
            expected_horizon=option.horizon_steps,
        )

        logger.info(
            "Remote linear regression forecast complete model=%s horizon=%s buffered_history_rows=%s",
            option.model_full_name,
            len(predictions),
            response.buffered_history_rows,
        )

        return PredictionResult(
            predictions=predictions,
            prediction_rows=response.predictions[: option.horizon_steps],
            current_time_origin=response.current_time_origin,
            world_cup_time_origin=response.world_cup_time_origin,
            remote_endpoint=option.endpoint,
            remote_contract=option.remote_contract,
            required_history_rows=response.required_context_rows,
            provided_history_rows=response.provided_history_rows,
            buffered_history_rows=response.buffered_history_rows,
        )

    def _build_linear_regression_history_rows(
        self,
        *,
        history: dict[str, list[float]],
        generated_at: datetime,
        step_seconds: int,
        required_rows: int,
    ) -> list[MetricForecastRow]:
        missing_metrics = [
            metric_name
            for metric_name in LINEAR_REGRESSION_HISTORY_METRICS
            if metric_name not in history
        ]
        if missing_metrics:
            raise ValueError(
                "Missing required metrics for linear regression contract: "
                + ", ".join(missing_metrics)
            )

        rows: list[MetricForecastRow] = []
        for offset in range(required_rows):
            row_timestamp = generated_at - timedelta(seconds=offset * step_seconds)
            rows.append(
                MetricForecastRow(
                    datetime=row_timestamp,
                    total_requests_per_minute=self._series_value_for_offset(
                        history["total_requests_per_minute"], offset
                    ),
                    total_cpu_seconds_per_minute=self._series_value_for_offset(
                        history["total_cpu_seconds_per_minute"], offset
                    ),
                    total_bandwidth_bytes_per_minute=self._series_value_for_offset(
                        history["total_bandwidth_bytes_per_minute"], offset
                    ),
                )
            )

        return rows

    def _series_value_for_offset(self, series: list[float], offset: int) -> float:
        index = len(series) - 1 - offset
        if index < 0:
            raise ValueError(
                f"History only contained {len(series)} points but offset {offset} was requested"
            )
        return float(series[index])

    def _extract_metric_predictions(
        self,
        *,
        response: LinearRegressionServingResponse,
        metric_name: str,
        expected_horizon: int,
    ) -> list[float]:
        if metric_name not in LINEAR_REGRESSION_HISTORY_METRICS:
            raise ValueError(
                f"Unsupported linear regression target metric '{metric_name}'. "
                f"Expected one of {', '.join(LINEAR_REGRESSION_HISTORY_METRICS)}"
            )

        if len(response.predictions) < expected_horizon:
            raise ValueError(
                f"Remote model returned {len(response.predictions)} prediction rows, "
                f"expected at least {expected_horizon}"
            )

        predictions: list[float] = []
        for row in response.predictions[:expected_horizon]:
            predictions.append(float(getattr(row, metric_name)))
        return predictions

    def _extract_predictions(
        self,
        payload: dict[str, Any],
        expected_horizon: int,
    ) -> list[float]:
        for key in ("predictions", "forecast", "values", "prediction"):
            value = payload.get(key)
            if value is None:
                continue

            if not isinstance(value, list):
                raise ValueError(
                    f"Remote model field '{key}' must be a list, got {type(value).__name__}"
                )

            predictions = [float(item) for item in value]
            if len(predictions) < expected_horizon:
                raise ValueError(
                    f"Remote model returned {len(predictions)} predictions, "
                    f"expected at least {expected_horizon}"
                )
            return predictions[:expected_horizon]

        raise ValueError(f"Remote model response missing prediction list: {payload}")

    def _aligned_now(self, step_seconds: int) -> datetime:
        now = datetime.now(UTC)
        aligned_timestamp = int(now.timestamp() // step_seconds) * step_seconds
        return datetime.fromtimestamp(aligned_timestamp, tz=UTC)
