from typing import Any

from pydantic import BaseModel, Field


class PrometheusSample(BaseModel):
    metric: dict[str, Any] = Field(default_factory=dict)
    value: list[Any]


class PrometheusData(BaseModel):
    result_type: str = Field(alias="resultType")
    result: list[PrometheusSample]


class PrometheusQueryResponse(BaseModel):
    status: str
    data: PrometheusData


class PredictionRequest(BaseModel):
    deployment_name: str | None = None
    prometheus_query: str | None = None
    current_replicas: int | None = Field(default=None, ge=1)
    target_metric_name: str = "requests_per_second"


class PredictionResponse(BaseModel):
    workload_prediction: float
    recommended_replicas: int
    replica: int
    metric_name: str
    query_used: str
    prometheus_value: float
    ai_server_used: bool
    deployment_name: str | None = None
    raw_ai_response: dict[str, Any] | None = None
