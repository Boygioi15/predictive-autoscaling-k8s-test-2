# forecasting-service

Small FastAPI service that:

- queries Prometheus inside the Kubernetes cluster
- calls an external AI server for workload prediction
- returns a simple JSON response that can be consumed by the custom scaler

## Endpoints

- `GET /health`
- `POST /predict-workload`

Example request:

```json
{
  "deployment_name": "prime-service-deployment",
  "target_metric_name": "requests_per_second"
}
```

Example response:

```json
{
  "workload_prediction": 8.4,
  "recommended_replicas": 2,
  "replica": 2,
  "metric_name": "requests_per_second",
  "query_used": "sum(rate(http_requests_total{job=\"prime-service\"}[2m]))",
  "prometheus_value": 7.9,
  "ai_server_used": true,
  "deployment_name": "prime-service-deployment",
  "raw_ai_response": {
    "prediction": 8.4
  }
}
```

## Environment variables

- `PROMETHEUS_BASE_URL`
- `PROMETHEUS_QUERY`
- `AI_SERVER_URL`
- `REPLICA_DIVISOR`
- `MIN_REPLICAS`
- `MAX_REPLICAS`
- `FALLBACK_PREDICTION_ENABLED`

## Local run

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8080
```
