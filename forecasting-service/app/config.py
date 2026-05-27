from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "forecasting-service"
    host: str = "0.0.0.0"
    port: int = 8080

    prometheus_base_url: str = "http://monitoring-stack-kube-prom-prometheus.monitoring.svc.cluster.local:9090"
    prometheus_query: str = (
        'sum(rate(http_requests_total{job="prime-service"}[2m]))'
    )
    prometheus_query_window: str = "2m"
    prometheus_timeout_seconds: float = Field(default=10.0, gt=0)

    ai_server_url: str = "http://127.0.0.1:9000/predict"
    ai_server_timeout_seconds: float = Field(default=15.0, gt=0)

    fallback_prediction_enabled: bool = True
    replica_divisor: float = Field(default=5.0, gt=0)
    min_replicas: int = Field(default=1, ge=1)
    max_replicas: int = Field(default=10, ge=1)


settings = Settings()
