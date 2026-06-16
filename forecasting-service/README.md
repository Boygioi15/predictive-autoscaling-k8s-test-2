# forecasting-service

FastAPI service that:

- resolves the active forecasting option for a deployment
- queries Prometheus for aligned historical range data
- runs a local heuristic model or calls a remote model endpoint
- returns a sequence forecast that the scaler can interpret

## Endpoints

- `GET /health`
- `POST /forecast`
- `POST /predict-workload`

`/predict-workload` is kept as a compatibility alias for the new forecast
contract.

## Request

```json
{
  "deployment": "prime-service"
}
```

`deployment_name` is also accepted as an input alias.

## Response

```json
{
  "deployment": "prime-service",
  "option_id": "prime-last-value-v1",
  "target_metric": "requests_per_minute",
  "feature_metrics": ["rps"],
  "step_seconds": 60,
  "predictions": [120.0, 120.0, 120.0, 120.0, 120.0],
  "observed": {
    "app_p95_seconds": [0.12, 0.15, 0.14, 0.13, 0.11],
    "ingress_p95_seconds": [0.16, 0.20, 0.18, 0.17, 0.15]
  },
  "model_name": "last_value",
  "model_version": "v1",
  "generated_at": "2026-06-05T10:30:00Z"
}
```

## Configuration Files

### `config/options.json`

Defines the available forecasting options.

Each option contains:

- target metric
- feature metrics
- lookback steps
- horizon steps
- step size
- model name/version
- Prometheus query or query map
- local/remote execution mode
- remote endpoint when needed

### `config/selection.json`

Defines the currently selected option per deployment.

Example:

```json
{
  "default_option_id": "prime-last-value-v1",
  "deployments": {
    "prime-service": "prime-last-value-v1"
  }
}
```

## Environment Variables

- `PROMETHEUS_BASE_URL`
- `PROMETHEUS_TIMEOUT_SECONDS`
- `REMOTE_MODEL_TIMEOUT_SECONDS`
- `FORECAST_OPTIONS_PATH`
- `FORECAST_SELECTION_PATH`
- `FORECAST_DEFAULT_OPTION_ID`
- `FORECAST_SELECTION_OVERRIDES`

Current default:

- `PROMETHEUS_TIMEOUT_SECONDS=30`

`FORECAST_SELECTION_OVERRIDES` uses:

```text
prime-service=prime-linear-regression-v1,text-service=text-last-value-v1
```

## Remote Model Contract

For remote options, the forecasting service sends:

```json
{
  "deployment": "prime-service",
  "target_metric": "requests_per_minute",
  "feature_metrics": ["rps"],
  "lookback_steps": 60,
  "horizon_steps": 5,
  "step_seconds": 60,
  "model_full_name": "linear_regression:v1",
  "generated_at": "2026-06-05T10:30:00Z",
  "history": {
    "rps": [101.0, 98.0, 104.0]
  }
}
```

Expected response shape:

```json
{
  "predictions": [120.0, 125.0, 128.0, 122.0, 119.0]
}
```

The service also accepts the keys `forecast`, `values`, or `prediction` if they
contain a prediction list.

## Local Models

Currently implemented locally:

- `last_value`

Remote serving is expected for learned models such as `linear_regression`.

## Local Run

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8080
```
