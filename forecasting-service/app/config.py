from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "forecasting-service"
    host: str = "0.0.0.0"
    port: int = 8080

    prometheus_base_url: str = (
        "http://monitoring-stack-kube-prom-prometheus.monitoring.svc.cluster.local:9090"
    )
    prometheus_timeout_seconds: float = Field(default=30.0, gt=0)

    remote_model_timeout_seconds: float = Field(default=15.0, gt=0)

    forecast_options_path: str = "config/options.json"


settings = Settings()
