import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .clients import PrometheusClient, RemoteModelClient
from .config import settings
from .models import (
    ForecastOption,
    ForecastRequest,
    ForecastResponse,
    ForecastSelection,
    RemotePredictionRequest,
)


logger = logging.getLogger(__name__)


class ForecastingService:
    def __init__(self) -> None:
        self.prometheus = PrometheusClient()
        self.remote_model = RemoteModelClient()

    async def predict_workload(self, request: ForecastRequest) -> ForecastResponse:
        deployment = request.deployment
        # load options, selection. 
        options = self._load_options()
        selection = self._load_selection()
        option_id = self._resolve_option_id(deployment, selection)
        if option_id not in options:
            raise KeyError(
                f"Active option '{option_id}' for deployment '{deployment}' was not found "
                f"in {settings.forecast_options_path}"
            )
        option = options[option_id]
        generated_at = self._aligned_now(option.step_seconds)

        logger.info(
            "Starting forecast deployment=%s option_id=%s model=%s generated_at=%s",
            deployment,
            option_id,
            option.model_full_name,
            generated_at.isoformat(),
        )

        history = await self._fetch_feature_history(
            deployment=deployment,
            option=option,
            generated_at=generated_at,
        )

        observed = await self._fetch_guardrail_history(
            deployment=deployment,
            option=option,
            generated_at=generated_at,
        )

        predictions = await self._predict(
            deployment=deployment,
            option=option,
            history=history,
            generated_at=generated_at,
        )

        return ForecastResponse(
            deployment=deployment,
            option_id=option_id,
            target_metric=option.target_metric,
            feature_metrics=option.feature_metrics,
            step_seconds=option.step_seconds,
            predictions=predictions,
            observed=observed,
            model_name=option.model_name,
            model_version=option.model_version,
            generated_at=generated_at,
        )

    def _load_options(self) -> dict[str, ForecastOption]:
        payload = self._load_json_file(settings.forecast_options_path)
        options: dict[str, ForecastOption] = {}

        for option_id, option_payload in payload.items():
            options[option_id] = ForecastOption.model_validate(option_payload)

        if not options:
            raise ValueError("No forecast options were loaded")

        return options

    def _load_selection(self) -> ForecastSelection:
        payload = self._load_json_file(settings.forecast_selection_path)
        return ForecastSelection.model_validate(payload)

    def _load_json_file(self, path_value: str) -> dict[str, Any]:
        path = Path(path_value)
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _resolve_option_id(self, deployment: str, selection: ForecastSelection) -> str:
        overrides = self._parse_selection_overrides(settings.forecast_selection_overrides)
        if deployment in overrides:
            return overrides[deployment]

        if deployment in selection.deployments:
            return selection.deployments[deployment]

        if settings.forecast_default_option_id:
            return settings.forecast_default_option_id

        if selection.default_option_id:
            return selection.default_option_id

        raise KeyError(
            f"No active forecast option configured for deployment '{deployment}'"
        )

    def _parse_selection_overrides(self, raw_value: str) -> dict[str, str]:
        overrides: dict[str, str] = {}
        for entry in raw_value.split(","):
            candidate = entry.strip()
            if not candidate:
                continue
            if "=" not in candidate:
                raise ValueError(
                    "FORECAST_SELECTION_OVERRIDES entries must use deployment=option_id format"
                )
            deployment, option_id = candidate.split("=", 1)
            overrides[deployment.strip()] = option_id.strip()
        return overrides

    async def _fetch_feature_history(
        self,
        *,
        deployment: str,
        option: ForecastOption,
        generated_at: datetime,
    ) -> dict[str, list[float]]:
        start = generated_at - timedelta(
            seconds=option.step_seconds * (option.lookback_steps - 1)
        )
        history: dict[str, list[float]] = {}

        for metric_name in option.feature_metrics:
            raw_query = option.query_for_metric(metric_name)
            query = self._render_query(raw_query, deployment)
            values = await self.prometheus.query_range(
                query,
                start=start,
                end=generated_at,
                step_seconds=option.step_seconds,
                expected_points=option.lookback_steps,
            )
            history[metric_name] = values
            logger.info(
                "Fetched Prometheus history deployment=%s metric=%s points=%s",
                deployment,
                metric_name,
                len(values),
            )

        return history

    async def _fetch_guardrail_history(
        self,
        *,
        deployment: str,
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
            query = self._render_query(raw_query, deployment)
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
                "Fetched Prometheus guardrail history deployment=%s metric=%s points=%s",
                deployment,
                metric_name,
                len(values),
            )

        return observed

    def _render_query(self, query: str, deployment: str) -> str:
        return query.replace("{{deployment}}", deployment)

    async def _predict(
        self,
        *,
        deployment: str,
        option: ForecastOption,
        history: dict[str, list[float]],
        generated_at: datetime,
    ) -> list[float]:
        if option.local:
            return self._predict_local(option=option, history=history)

        payload = RemotePredictionRequest(
            deployment=deployment,
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
            "Remote forecast complete deployment=%s model=%s horizon=%s",
            deployment,
            option.model_full_name,
            len(predictions),
        )
        return predictions

    def _predict_local(
        self,
        *,
        option: ForecastOption,
        history: dict[str, list[float]],
    ) -> list[float]:
        model_name = option.model_name

        if model_name == "last_value":
            primary_metric = option.feature_metrics[0]
            series = history.get(primary_metric, [])
            last_value = series[-1] if series else 0.0
            return [last_value] * option.horizon_steps

        raise ValueError(
            f"Unsupported local model '{option.model_full_name}'. "
            "Only last_value is implemented locally right now."
        )

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
