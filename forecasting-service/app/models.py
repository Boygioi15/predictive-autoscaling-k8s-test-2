from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import AliasChoices, BaseModel, Field, model_validator


class PrometheusRangeSample(BaseModel):
    metric: dict[str, Any] = Field(default_factory=dict)
    values: list[list[Any]]


class PrometheusData(BaseModel):
    result_type: str = Field(alias="resultType")
    result: list[PrometheusRangeSample]


class PrometheusQueryRangeResponse(BaseModel):
    status: str
    data: PrometheusData


class ForecastRequest(BaseModel):
    contract_id: str = Field(
        validation_alias=AliasChoices("contract_id", "option_id"),
        min_length=1,
    )


class ForecastResponse(BaseModel):
    deployment: str
    contract_id: str
    target_metric: str
    feature_metrics: list[str]
    step_seconds: int = Field(ge=1)
    predictions: list[float]
    observed: dict[str, list[float | None]] = Field(default_factory=dict)
    model_name: str
    model_version: str
    generated_at: datetime
    prediction_rows: list[MetricForecastRow] = Field(default_factory=list)
    current_time_origin: datetime | None = None
    world_cup_time_origin: datetime | None = None
    remote_endpoint: str | None = None
    remote_contract: str | None = None
    required_history_rows: int | None = None
    provided_history_rows: int | None = None
    buffered_history_rows: int | None = None


class ForecastOption(BaseModel):
    deployment: str
    namespace: str = "default"
    service: str
    ingress: str
    app_pod_regex: str
    target_metric: str
    remote_target_metric: str | None = None
    feature_metrics: list[str]
    guardrail_queries: dict[str, str] | None = None
    lookback_steps: int = Field(ge=1)
    horizon_steps: int = Field(ge=1)
    step_seconds: int = Field(ge=1)
    model_full_name: str
    prometheus_query: str | None = None
    prometheus_queries: dict[str, str] | None = None
    local: bool = False
    endpoint: str | None = None
    remote_contract: str = "legacy_prediction_list"

    @model_validator(mode="after")
    def validate_configuration(self) -> ForecastOption:
        has_single_query = bool(self.prometheus_query)
        has_query_map = bool(self.prometheus_queries)

        if not has_single_query and not has_query_map:
            raise ValueError("Forecast option must define prometheus_query or prometheus_queries")

        if self.local and self.endpoint:
            raise ValueError("Local forecast option must not define endpoint")

        if not self.local and not self.endpoint:
            raise ValueError("Remote forecast option must define endpoint")

        return self

    @property
    def model_name(self) -> str:
        return self.model_full_name.split(":", 1)[0]

    @property
    def model_version(self) -> str:
        if ":" not in self.model_full_name:
            return "latest"
        return self.model_full_name.split(":", 1)[1]

    def query_for_metric(self, metric_name: str) -> str:
        if self.prometheus_queries:
            query = self.prometheus_queries.get(metric_name)
            if query is not None:
                return query

        if self.prometheus_query:
            return self.prometheus_query

        raise KeyError(f"No Prometheus query configured for feature metric '{metric_name}'")


class RemotePredictionRequest(BaseModel):
    deployment: str
    target_metric: str
    feature_metrics: list[str]
    lookback_steps: int = Field(ge=1)
    horizon_steps: int = Field(ge=1)
    step_seconds: int = Field(ge=1)
    model_full_name: str
    generated_at: datetime
    history: dict[str, list[float]]


class RemotePredictionResponse(BaseModel):
    predictions: list[float]


class MetricForecastRow(BaseModel):
    datetime: datetime
    total_requests_per_minute: float
    total_cpu_seconds_per_minute: float
    total_bandwidth_bytes_per_minute: float


class LinearRegressionServingRequest(BaseModel):
    current_time_origin: datetime
    history: list[MetricForecastRow] = Field(min_length=1)


class LinearRegressionServingResponse(BaseModel):
    model: str
    version: str
    model_path: str | None = None
    timestamp_column: str = "datetime"
    input_columns: list[str] = Field(default_factory=list)
    target_columns: list[str] = Field(default_factory=list)
    current_time_origin: datetime
    world_cup_time_origin: datetime
    configured_real_time_anchor: datetime | None = None
    configured_world_cup_time_anchor: datetime | None = None
    horizon: int = Field(ge=1)
    required_context_rows: int | None = None
    provided_history_rows: int | None = None
    buffered_history_rows: int | None = None
    predictions: list[MetricForecastRow] = Field(default_factory=list)
