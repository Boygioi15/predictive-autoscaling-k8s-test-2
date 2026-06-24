# Custom Load Generator

## Goal

This directory contains a custom Python sender for replaying `shares/test_script.csv` as an open-loop arrival trace without the framework overhead of Locust or k6.

The main design target is:

- treat the CSV as the source of truth for desired request arrivals
- keep client resource usage bounded
- avoid hidden backlog inside the generator
- preserve the existing output files used by the notebook flow

The runtime entrypoint is [load_sender.py](/home/boygioi15/predictive-autoscaling-k8s-test/custom-load-generator/load_sender.py), and the deterministic workload builder is [workload.py](/home/boygioi15/predictive-autoscaling-k8s-test/custom-load-generator/workload.py).

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
- one bounded in-flight token pool per worker process
- one async HTTP client session per worker process

So the controlling resource is not "how many VUs are initialized", but:

- how many request slots are allowed to be in flight at once

That is `MAX_INFLIGHT`.

When `WORKER_COUNT > 1`, the sender launches multiple Python worker processes. Each worker:

- gets its own event loop
- gets its own token pool sized by `MAX_INFLIGHT`
- handles a deterministic shard of the global request stream

This is the intended way to use more CPU cores on the generator side, since a single `asyncio` process mostly runs on one core.

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

`WorkloadPlanner` builds a deterministic per-request-class sequence from env vars such as:

- `REQUEST_CLASSES`
- `DEMAND_BASE_PATH`
- `SCRIPT_RANDOM_SEED`

The planner does not change the per-second traffic shape from the CSV.
It expands each second directly from the CSV request-class count columns and ignores the legacy `requests` field.

For each second:

- it reads the `type_*` columns that correspond to `REQUEST_CLASSES`
- the total requests for that second is the sum of those class counts
- requests are emitted in `REQUEST_CLASSES` order
- each class is repeated exactly as many times as its CSV count for that second

With the default config, the sequence is:

- `directory`
- then `image`
- then `html`
- then `other`
- then `audio`
- then `java`
- then `video`
- then `compressed`
- then `dynamic`

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

With multiple workers enabled, this bounded dispatch happens independently inside each worker process. Effective total in-flight capacity becomes approximately:

- `WORKER_COUNT * MAX_INFLIGHT`

and each worker only sees the requests assigned to its shard.

## Multi-Worker Implementation

`WORKER_COUNT` does not create Python threads.

It creates multiple **Python worker processes**.

That choice is intentional:

- one `asyncio` process mostly runs on one CPU core
- Python threads would still share one interpreter process
- separate processes give separate event loops and much better multi-core use

The implementation works like this.

### 1. Parent launcher

When:

- `WORKER_COUNT > 1`
- and `WORKER_INDEX` is not set

the main process becomes a launcher.

It:

- loads the normalized CSV timeline once
- writes the shared metadata file once
- spawns `WORKER_COUNT` child processes
- gives each child its own temporary report paths
- waits for all children to finish
- merges child reports into the normal final output files

So the parent is only an orchestrator. It does not send HTTP requests itself in this mode.

### 2. Worker identity

Each child process gets:

- `WORKER_INDEX`
- `WORKER_COUNT`

For example, with `WORKER_COUNT=4`, the children run as:

- worker `0`
- worker `1`
- worker `2`
- worker `3`

Each worker still runs the same sender code. The only difference is which requests it is responsible for.

### 3. Deterministic request sharding

The full script trace is treated as one global request stream.

Each request has a deterministic global request index:

- `global_request_index`

computed from:

- all requests in earlier script seconds
- plus the request position within the current second

Then sharding is:

- worker handles request if `global_request_index % WORKER_COUNT == WORKER_INDEX`

So with 4 workers:

- worker 0 handles indices `0, 4, 8, ...`
- worker 1 handles indices `1, 5, 9, ...`
- worker 2 handles indices `2, 6, 10, ...`
- worker 3 handles indices `3, 7, 11, ...`

This gives:

- stable assignment across runs
- even distribution of requests
- deterministic workload generation per worker

### 4. Per-worker sender resources

Each worker process creates its own:

- `asyncio` event loop
- `aiohttp.ClientSession`
- inflight token pool
- backlog queue
- progress logger

This means the worker resources are **not shared**.

So if:

- `WORKER_COUNT=4`
- `MAX_INFLIGHT=500`

then total effective in-flight budget is about:

- `4 * 500 = 2000`

The same rule applies to backlog:

- `BACKLOG_CAPACITY` is also per worker

So multi-worker runs should usually reduce those per-worker values if you want to keep total pressure similar to the single-worker baseline.

### 5. Per-worker temporary outputs

Each worker writes to temporary files such as:

- `load_generator_request_report.worker0.csv`
- `load_generator_request_report.worker1.csv`

and similarly for:

- statistics report
- incident report

This avoids workers writing into the same CSV at the same time.

### 6. Merge step

After all workers exit, the parent merges the temporary files:

- request report rows are summed by `(second, url)`
- statistics report rows are summed by `second`
- incident report rows are concatenated and sorted

Then the merged results are written back to the normal final outputs:

- `load_generator_request_report.csv`
- `load_generator_statistics_report.csv`
- `load_generator_incident_report.csv`

Finally, the temporary worker files are removed.

### 7. Metadata handling

The metadata file is written only by the parent launcher in multi-worker mode.

Child workers do not rewrite it.

This keeps:

- one consistent run start time
- one consistent script summary

instead of having workers race to overwrite shared metadata.

### 5. Optional bounded backlog

The sender can also run with a bounded FIFO backlog:

- `BACKLOG_CAPACITY`
- `BACKLOG_MAX_AGE_SECONDS`

If no token is free at schedule time and backlog is enabled:

- the request is appended to the backlog
- it waits for a token to become free
- if it waits too long, it expires and is dropped
- if the backlog is full, it is dropped immediately

This gives a middle ground between:

- exact punctuality with no retry opportunity
- and an unbounded hidden queue

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

### `enqueued_requests`

How many scheduled requests were placed into the bounded backlog instead of being started immediately.

### `started_requests`

How many requests successfully acquired an in-flight token and were actually launched.

This is the best current meaning of:

- sent
- started on the generator side

### `started_immediate_requests`

How many requests started immediately at schedule time.

### `started_from_backlog_requests`

How many requests were delayed in backlog and later started when a token freed up.

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

How many requests were ultimately lost because the sender could not place them.

With backlog disabled, this means:

- all in-flight tokens were occupied at schedule time

With backlog enabled, this includes:

- backlog full at schedule time
- backlog items that expired before they could start

### `dropped_backlog_full_requests`

How many requests were dropped because backlog was enabled but already full.

### `backlog_expired_requests`

How many requests were enqueued but waited longer than `BACKLOG_MAX_AGE_SECONDS`, so they were dropped before starting.

## About "Enqueued"

When `BACKLOG_CAPACITY=0`, there is no backlog queue stage.

That means:

- we do not currently have an "enqueued and waiting for later send" metric

This is deliberate for the strict no-backlog mode.

If we added a real waiting queue, we would reintroduce the same problem we wanted to avoid:

- the sender would look like it is keeping up
- but actual request starts would silently trail behind the trace

So the no-backlog state machine is:

1. planned in CSV
2. scheduled now
3. either started or dropped for capacity
4. if started, then completed / failed / timed out

With bounded backlog enabled, the state machine becomes:

1. planned in CSV
2. scheduled now
3. either started immediately, enqueued, or dropped if backlog is full
4. enqueued requests either start later or expire
5. started requests then complete / fail / time out

## Output Files

The sender preserves the existing output contract.

### `shares/load_generator_metadata.csv`

This contains:

- `run_start_time`
- `run_start_second`
- `script_path`
- `script_start_time`
- `script_end_time`
- `script_seconds`
- `planned_requests`

### `shares/load_generator_request_report.csv`

This contains:

- `second`
- `url`
- `count`

This file records generator-side started requests grouped by:

- wall-clock second
- canonical URL

It does not record dropped requests. Those remain in runtime logs and in-memory counters.

### `shares/load_generator_statistics_report.csv`

This contains one row per wall-clock second with:

- `planned`
- `scheduled`
- `enqueued`
- `started`
- `started_immediate`
- `started_from_backlog`
- `completed`
- `failed`
- `timed_out`
- `dropped_capacity`
- `dropped_backlog_full`
- `backlog_expired`

This file is the quickest way to explain dips in the started-request graph.

Some useful interpretations:

- `planned - scheduled` should usually stay near `0`
- `planned - started` shows the visible gap between intended and actually launched traffic
- `scheduled - enqueued - started_immediate` is the strict on-time loss before backlog rescue
- `scheduled - started` during the same second usually shows immediate capacity pressure
- `enqueued` shows how much work needed buffering
- `started_from_backlog` shows how much work backlog successfully rescued
- `dropped_capacity` shows requests that were ultimately lost
- `completed + failed + timed_out` explains how fast in-flight slots were released
- cumulative `started - completed - failed - timed_out` approximates in-flight load

### `shares/load_generator_incident_report.csv`

This records one row per matching incident with:

- `timestamp`
- `second`
- `url`
- `incident_type`
- `message`

Right now it is intentionally filtered to:

- `Connection reset by peer`

This file is meant for correlation against dips, not as a full error log.

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

- [Dockerfile](/home/boygioi15/predictive-autoscaling-k8s-test/custom-load-generator/Dockerfile)
- [custom_load_generator.env](/home/boygioi15/predictive-autoscaling-k8s-test/custom-load-generator/custom_load_generator.env)

The request script is packaged into the image at `/app/scripts/test_script.csv`, and runtime reports are written under `/app/output`.

From repo root:

```bash
make build-custom-load-generator
make run-custom-load-generator
```

## Future Extensions

If needed, the next useful extensions would be:

- write a small run-summary JSON or CSV with `scheduled`, `started`, `completed`, `failed`, `timed_out`, and `dropped_due_to_capacity`
- add per-minute snapshots to a separate report file
- move to Go only if Python itself becomes the bottleneck
