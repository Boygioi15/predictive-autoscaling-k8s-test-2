# Custom Load Test

## Goal

This directory contains a custom Python sender for replaying `shares/test_script.csv` as an open-loop arrival trace without the framework overhead of Locust or k6.

The main design target is:

- treat the CSV as the source of truth for desired request arrivals
- keep client resource usage bounded
- avoid hidden backlog inside the generator
- preserve the existing output files used by the notebook flow

The runtime entrypoint is [load_sender.py](/home/boygioi15/predictive-autoscaling-k8s-test/custom-load-test/load_sender.py), and the deterministic workload builder is [workload.py](/home/boygioi15/predictive-autoscaling-k8s-test/custom-load-test/workload.py).

## Big Idea

The sender separates two concerns:

1. Traffic shape
   - read `shares/test_script.csv`
   - normalize it into one bucket per second
   - fill missing seconds as zero

2. Request semantics
   - choose which endpoint to call
   - generate parameters and payloads
   - keep that choice deterministic from a seed

This means:

- the CSV answers "how many requests should be attempted at second `t`"
- the workload config answers "what should each request look like"

## Why This Is Different From Locust And k6

This sender does not create virtual users or scenarios.

Instead, it uses:

- one scheduler clock
- one bounded in-flight token pool
- one async HTTP client session

So the controlling resource is not "how many VUs are initialized", but:

- how many request slots are allowed to be in flight at once

That is `MAX_INFLIGHT`.

## Execution Model

The run has four layers.

### 1. CSV normalization

`load_script_points()` reads the input CSV and enforces:

- required columns: `datetime,requests`
- timestamps must be timezone-aware
- timestamps must be sorted ascending after UTC normalization
- duplicate normalized seconds are rejected
- missing seconds are inserted explicitly as `0`

The result is a canonical list of:

- `ScriptPoint(timestamp, requests)`

### 2. Workload planning

`WorkloadPlanner` builds a deterministic weighted cycle of operations from env vars such as:

- `PRIME_USER_WEIGHT`
- `TEXT_USER_WEIGHT`
- `SCRIPT_RANDOM_SEED`

Each scheduled request is mapped to a request shape using:

- the global seed
- `second_index`
- `request_index_within_second`
- `scheduled_index`

That gives deterministic replay without storing a giant pre-expanded request table.

### 3. Open-loop scheduling

For each script second:

- in `burst` mode, requests for that second are launched immediately
- in `spread` mode, requests are spaced across the second

Important detail:

- the scheduler does not wait for previous responses before attempting new requests

That is the open-loop part.

### 4. Bounded dispatch

Before a request is launched, the sender must acquire one token from an `asyncio.Queue` pre-filled with `MAX_INFLIGHT` tokens.

If a token is available:

- the request is started immediately
- one async task is created for that request

If no token is available:

- the request is not queued for later
- it is counted as `dropped_due_to_capacity`

This is intentional.

The design choice here is:

- do not hide overload behind backlog
- make missed capacity visible immediately

## Timeout Model

The sender enforces timeouts in two places:

- `aiohttp.ClientTimeout`
- `asyncio.timeout(...)`

The practical meaning is:

- a request may occupy an in-flight slot for at most about `REQUEST_TIMEOUT_SECONDS`

This is closer to the real goal than framework-level transport knobs alone, because the sender itself owns the wall-clock lifetime of each request task.

## Counter Semantics

These are the most important runtime counters.

### `total_planned_requests`

The total sum of `requests` in the normalized CSV timeline.

This is the full expected trace for the whole run.

### `scheduled_requests`

How many planned requests have reached their scheduled send moment so far.

This is the best current meaning of:

- expected to send so far

It increases whether the request is actually launched or dropped for capacity.

### `started_requests`

How many requests successfully acquired an in-flight token and were actually launched.

This is the best current meaning of:

- sent
- started on the generator side

### `completed_requests`

How many launched requests finished with HTTP status `< 400`.

### `failed_requests`

How many launched requests finished with:

- HTTP status `>= 400`
- `aiohttp` client errors
- unexpected request exceptions

### `timed_out_requests`

How many launched requests hit the sender-side wall-clock timeout.

These are separated from generic failures because they usually mean:

- the server or network held the slot too long

### `dropped_due_to_capacity`

How many scheduled requests were not launched because all in-flight tokens were already occupied.

This is the important replacement for an internal queue backlog.

## About "Enqueued"

There is no backlog queue stage in this design.

That means:

- we do not currently have an "enqueued and waiting for later send" metric

This is deliberate.

If we added a real waiting queue, we would reintroduce the same problem we wanted to avoid:

- the sender would look like it is keeping up
- but actual request starts would silently trail behind the trace

So the current state machine is:

1. planned in CSV
2. scheduled now
3. either started or dropped for capacity
4. if started, then completed / failed / timed out

## Output Files

The sender preserves the existing output contract.

### `shares/load_test_metadata.csv`

This contains:

- `run_start_time`
- `run_start_second`
- `script_path`
- `script_start_time`
- `script_end_time`
- `script_seconds`
- `planned_requests`

### `shares/load_test_request_report.csv`

This contains:

- `second`
- `url`
- `count`

This file records generator-side started requests grouped by:

- wall-clock second
- canonical URL

It does not record dropped requests. Those remain in runtime logs and in-memory counters.

### `shares/load_test_statistics_report.csv`

This contains one row per wall-clock second with:

- `planned`
- `scheduled`
- `started`
- `completed`
- `failed`
- `timed_out`
- `dropped_capacity`

This file is the quickest way to explain dips in the started-request graph.

Some useful interpretations:

- `planned - scheduled` should usually stay near `0`
- `planned - started` shows the visible gap between intended and actually launched traffic
- `scheduled - started` during the same second usually shows immediate capacity pressure
- `dropped_capacity` shows requests that were refused instead of queued
- `completed + failed + timed_out` explains how fast in-flight slots were released
- cumulative `started - completed - failed - timed_out` approximates in-flight load

## Logging

The sender logs progress every `PROGRESS_LOG_INTERVAL_SEC`, currently intended to be 60 seconds.

The progress log is meant to answer quickly:

- how far through the script we are
- how many total planned requests exist in the whole script
- how many requests have reached schedule time so far
- how many requests were actually started
- how many finished successfully
- how many failed or timed out
- how many were dropped because capacity was full
- how many slots are still in flight

## Resource Model

The most important resource control is:

- `MAX_INFLIGHT`

This is the hard upper bound on concurrent in-flight requests from the sender.

Very roughly:

- throughput ceiling is limited by `MAX_INFLIGHT / average_request_lifetime`

So if:

- `MAX_INFLIGHT = 2000`
- average request lifetime is about `0.2s`

then the theoretical upper bound is around:

- `10,000 started requests/sec`

Real throughput will be lower because of:

- Python runtime overhead
- socket scheduling
- connection setup and reuse
- HTTP parsing
- kernel and network behavior
- target server behavior

## Current Tradeoff

This sender is not trying to guarantee:

- every planned request is eventually sent

It is trying to guarantee:

- every planned request is evaluated at its scheduled time
- the sender never hides overload behind unbounded internal backlog

That tradeoff is what makes the implementation simpler and the resource behavior more honest.

## Run Path

The Docker service and env file are:

- [Dockerfile](/home/boygioi15/predictive-autoscaling-k8s-test/custom-load-test/Dockerfile)
- [custom_load_test.env](/home/boygioi15/predictive-autoscaling-k8s-test/custom-load-test/custom_load_test.env)

From repo root:

```bash
make build-custom-load-test
make run-custom-load-test
```

## Future Extensions

If needed, the next useful extensions would be:

- write a small run-summary JSON or CSV with `scheduled`, `started`, `completed`, `failed`, `timed_out`, and `dropped_due_to_capacity`
- add per-minute snapshots to a separate report file
- add an optional bounded waiting queue if you explicitly want "enqueued" as a real stage
- move to Go only if Python itself becomes the bottleneck
