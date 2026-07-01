from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "system-showcase"
    host: str = "0.0.0.0"
    port: int = 8080
    base_path: str = Field(default="/system-showcase", validation_alias="SYSTEM_SHOWCASE_BASE_PATH")

    prometheus_base_url: str = Field(
        default="http://monitoring-stack-kube-prom-prometheus.monitoring.svc.cluster.local:9090",
        validation_alias="PROMETHEUS_BASE_URL",
    )
    prometheus_timeout_seconds: float = Field(
        default=20.0,
        gt=0,
        validation_alias="PROMETHEUS_TIMEOUT_SECONDS",
    )
    metrics_window_minutes: int = Field(
        default=20,
        ge=5,
        validation_alias="SYSTEM_SHOWCASE_METRICS_WINDOW_MINUTES",
    )
    metrics_step_seconds: int = Field(
        default=60,
        ge=15,
        validation_alias="SYSTEM_SHOWCASE_METRICS_STEP_SECONDS",
    )

    cache_ttl_seconds: int = Field(
        default=5,
        ge=1,
        validation_alias="SYSTEM_SHOWCASE_CACHE_TTL_SECONDS",
    )

    scaler_namespace: str = Field(default="default", validation_alias="SYSTEM_SHOWCASE_SCALER_NAMESPACE")
    scaler_name: str = Field(default="customscaler-sample", validation_alias="SYSTEM_SHOWCASE_SCALER_NAME")

    app_namespace: str = Field(default="default", validation_alias="SYSTEM_SHOWCASE_APP_NAMESPACE")
    app_service_name: str = Field(default="", validation_alias="SYSTEM_SHOWCASE_APP_SERVICE_NAME")
    app_ingress_name: str = Field(default="", validation_alias="SYSTEM_SHOWCASE_APP_INGRESS_NAME")
    app_pod_regex: str = Field(default="", validation_alias="SYSTEM_SHOWCASE_APP_POD_REGEX")

    controller_namespace: str = Field(
        default="custom-scaler-system",
        validation_alias="SYSTEM_SHOWCASE_CONTROLLER_NAMESPACE",
    )
    controller_deployment_name: str = Field(
        default="custom-scaler-controller-manager",
        validation_alias="SYSTEM_SHOWCASE_CONTROLLER_DEPLOYMENT_NAME",
    )
    worker_jobs_namespace: str = Field(
        default="custom-scaler-system",
        validation_alias="SYSTEM_SHOWCASE_WORKER_JOBS_NAMESPACE",
    )

    load_test_data_dir: str = Field(
        default="/tmp/system-showcase",
        validation_alias="SYSTEM_SHOWCASE_LOAD_TEST_DATA_DIR",
    )

    @property
    def normalized_base_path(self) -> str:
        value = self.base_path.strip() or "/system-showcase"
        if not value.startswith("/"):
            value = f"/{value}"
        return value.rstrip("/") or "/system-showcase"

    @property
    def frontend_dist_dir(self) -> Path:
        return Path(__file__).resolve().parent.parent / "frontend-dist"

    @property
    def load_test_dir(self) -> Path:
        return Path(self.load_test_data_dir)


settings = Settings()
