# forecasting-service

FastAPI service that:

- accepts a `contract_id`
- loads the matching deployment-specific contract from `config/options.json`
- queries Prometheus for the contract’s workload signals
- calls a local heuristic or the remote linear-regression model endpoint
- returns a scaler-friendly request forecast plus optional full prediction rows

## Endpoints

- `GET /health`
- `GET /`
- `POST /forecast`
- `POST /predict-workload`

`/predict-workload` is a compatibility alias for `/forecast`.

## Request

```json
{
  "contract_id": "demo-linear-regression-v1"
}
```

`option_id` is also accepted as an input alias for compatibility.

## Response

```json
{
  "deployment": "demo-app",
  "contract_id": "demo-linear-regression-v1",
  "target_metric": "requests_per_minute",
  "feature_metrics": [
    "total_requests_per_minute",
    "total_cpu_seconds_per_minute",
    "total_bandwidth_bytes_per_minute"
  ],
  "step_seconds": 60,
  "predictions": [1599.6, 1584.2, 1570.1],
  "prediction_rows": [
    {
      "datetime": "2026-06-25T01:01:00Z",
      "total_requests_per_minute": 1599.6,
      "total_cpu_seconds_per_minute": 30.44,
      "total_bandwidth_bytes_per_minute": 22896339.7
    }
  ],
  "observed": {
    "app_error_rate": [0.01, 0.02, 0.06],
    "ingress_p99_seconds": [0.14, 0.16, 0.15]
  },
  "model_name": "linear_regression",
  "model_version": "v1",
  "generated_at": "2026-06-25T01:00:00Z",
  "current_time_origin": "2026-06-25T01:00:00Z",
  "world_cup_time_origin": "1998-06-08T15:00:00Z",
  "remote_endpoint": "http://100.98.89.128:8000/predict/linear_regression/v1",
  "remote_contract": "linear_regression_serving_v1",
  "required_history_rows": 61,
  "provided_history_rows": 61,
  "buffered_history_rows": 0
}
```

## Contract Files

### `config/options.json`

Each entry is now a self-contained, deployment-specific contract.

A contract contains:

- deployment metadata
  - `deployment`
  - `namespace`
  - `service`
  - `ingress`
  - `app_pod_regex`
- forecast behavior
  - `target_metric`
  - `feature_metrics`
  - `lookback_steps`
  - `horizon_steps`
  - `step_seconds`
- Prometheus queries
- model routing
  - `model_full_name`
  - `local`
  - `endpoint`
  - `remote_contract`

Current packaged contracts:

- `demo-last-value-v1`
- `demo-linear-regression-v1`

## Current Prometheus Inputs

The packaged linear-regression contract queries these three workload signals:

- `total_requests_per_minute`
- `total_cpu_seconds_per_minute`
- `total_bandwidth_bytes_per_minute`

Current packaged queries are:

```promql
sum(
  increase(
    nginx_ingress_controller_requests[1m]
  )
)
```

```promql
sum(
  increase(
    container_cpu_usage_seconds_total{
      namespace="{{namespace}}",
      pod=~"{{app_pod_regex}}",
      container!="POD",
      container!=""
    }[1m]
  )
)
```

```promql
sum(
  increase(
    container_network_transmit_bytes_total{
      namespace="{{namespace}}",
      pod=~"{{app_pod_regex}}"
    }[1m]
  )
)
```

The packaged contracts also return these observed guardrail signals for the
custom scaler:

- `app_error_rate`
- `ingress_p99_seconds`

`app_error_rate` is fetched as the 1-minute 5xx fraction for the scraped app
service:

```promql
(
  (sum(increase(http_requests_total{service="{{service}}",status=~"5.."}[1m])) or on() vector(0))
  /
  clamp_min((sum(increase(http_requests_total{service="{{service}}"}[1m])) or on() vector(0)), 1)
)
```

## Remote Linear Regression Contract

For `demo-linear-regression-v1`, the service converts Prometheus samples into
the model endpoint contract documented in
[../LINEAR_REGRESSION_SERVING_CONTRACT.md](../LINEAR_REGRESSION_SERVING_CONTRACT.md).

The forecasting service sends:

```json
{
  "current_time_origin": "2026-06-25T01:00:00Z",
  "history": [
    {
      "datetime": "2026-06-25T01:00:00Z",
      "total_requests_per_minute": 1565.0,
      "total_cpu_seconds_per_minute": 29.61,
      "total_bandwidth_bytes_per_minute": 19927430.0
    },
    {
      "datetime": "2026-06-25T00:59:00Z",
      "total_requests_per_minute": 1601.0,
      "total_cpu_seconds_per_minute": 30.66,
      "total_bandwidth_bytes_per_minute": 23209850.0
    }
  ]
}
```

Important details:

- `current_time_origin` is the aligned current minute used for this forecast.
- `history` is reverse chronological: newest row first.
- the packaged linear-regression contract sends `61` rows to match the model’s
  required context window.
- the remote model still owns any internal anchored-time logic and optional
  history buffering.

## Environment Variables

- `PROMETHEUS_BASE_URL`
- `PROMETHEUS_TIMEOUT_SECONDS`
- `REMOTE_MODEL_TIMEOUT_SECONDS`
- `FORECAST_OPTIONS_PATH`

## Local Run

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8080
```
