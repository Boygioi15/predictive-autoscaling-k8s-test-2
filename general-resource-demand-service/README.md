## General Resource Demand Service

This service exposes request-class endpoints backed by resource-demand profiles.

The first prototype models:

- thread CPU demand
- response payload demand

Each accepted request:

- samples CPU demand from `config/cpu-demand-profiles.json`
- samples response payload demand from `config/response-payload-demand-profiles.json`
- occupies one worker thread while it burns CPU until the measured thread CPU time reaches the sampled target
- enters a bounded in-memory queue when all worker threads are busy
- returns a response body whose size matches the sampled response payload target

Only request classes present in both profile files become active endpoints.

## Profile Files

The service reads two external profile lists:

- `config/cpu-demand-profiles.json`
- `config/response-payload-demand-profiles.json`

CPU demand profiles contain one entry per request class:

```json
{
  "baseThreadCpuMs": 5,
  "cpuNoiseLimitMs": 3,
  "requestClassWeights": {
    "image": 1
  }
}
```

Response payload demand profiles also contain one entry per request class:

```json
[
  {
    "requestClass": "image",
    "p01Bytes": 0,
    "p05Bytes": 0,
    "p10Bytes": 0,
    "p25Bytes": 94,
    "p50Bytes": 685,
    "p75Bytes": 1312,
    "p90Bytes": 3310,
    "p95Bytes": 7514,
    "p99Bytes": 17134
  }
]
```

CPU demand uses the configured weighted model:

- base thread CPU cost: `5 ms`
- endpoint weight:
  `DIRECTORY=1`, `IMAGE=1`, `HTML=2`, `OTHER=2`, `AUDIO=2`, `JAVA=3`, `VIDEO=3`, `COMPRESSED=4`, `DYNAMIC=8`
- additive noise: a double sampled from `[-3 ms, +3 ms)`

So the target thread CPU time is:

```text
targetThreadCpuMs = 5 * weight + noise
```

Response payload demand profiles use percentile buckets only. The service rolls an integer from `1` to `100` and samples uniformly inside the matching percentile band.

Examples:

- `r = 5` samples between `p05Bytes` and `p10Bytes`
- `r = 90` samples between `p90Bytes` and `p95Bytes`
- `r = 99` or `r = 100` returns `p99Bytes`

## Endpoints

- `GET /` returns the service summary and configured request classes
- `GET /demand` returns the merged request-class profiles
- `GET /demand/:requestClass` executes one sampled request for that request class
- `GET /demand/:requestClass?format=json` returns metrics as JSON instead of the raw payload
- `GET /metrics` exposes Prometheus metrics

`GET /demand/:requestClass` returns:

- a binary response body sized to the sampled response payload demand
- verification metadata in response headers such as:
  `Content-Length`, `X-Observed-Thread-CPU-Ms`, `X-Target-Thread-CPU-Ms`, `X-Queue-Wait-Ms`, and `X-App-Time-Ms`

## Worker Pool And Queue

The resource-demand execution path is sized through constants in `src/resource-demand/resource-demand.constants.ts`:

- worker pool size: `WORKER_POOL_SIZE = 6`
- bounded pending queue size: `PENDING_QUEUE_SIZE = 12`

Behavior:

- if a worker is free, the request starts immediately
- if all workers are busy and the queue has space, the request waits in the queue
- if both the worker pool and queue are full, the service rejects the request with `503 Service Unavailable`

## Project setup

```bash
npm install
```

## Run the service

```bash
npm run start
npm run start:dev
npm run start:prod
```

## Docker

```bash
docker build -t general-resource-demand-service .
docker run --rm -p 3000:3000 general-resource-demand-service
```

## Runtime constants

The prototype currently uses fixed constants from `src/resource-demand/resource-demand.constants.ts`, including:

- `APP_PORT = 3000`
- `WORKER_POOL_SIZE = 6`
- `PENDING_QUEUE_SIZE = 12`
