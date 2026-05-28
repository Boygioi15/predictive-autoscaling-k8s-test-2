# Locust Work Log

## Goal

The core goal of this Locust setup is:

- read a scripted CSV where each row represents one second
- at scripted second `t`, attempt to send exactly `requests[t]` HTTP requests
- compare three views side by side:
  - `test_request`: what the script planned
  - `locust_request`: what Locust started sending
  - `ingress_request`: what ingress actually received

This means the test is not primarily about user behavior. It is mainly about request scheduling and verification.

## High-Level Architecture

The current script-mode architecture in `locust-test/` is:

- `locustfile.py`
  - switches between `manual` mode and `script` mode
- `script_scheduler.py`
  - owns the CSV timeline, scheduling, worker pool, progress logs, and run metadata
- `workload.py`
  - defines what each request actually is
  - also records the Locust-side per-second request report
- `shares/test_script.csv`
  - the sliced input script used for a run
- `shares/locust_request_report.csv`
  - Locust-side per-second send-attempt report
- `shares/locust_run_metadata.csv`
  - run start metadata for wall-clock alignment

Script mode still uses one dummy Locust user, but that user is only there to keep Locust running. The real traffic comes from the scheduler, not from normal looping `@task` users.

## CSV Planner

The planner step converts the CSV into an ordered timeline:

```python
[
  (datetime(...12:30:00...), 124),
  (datetime(...12:30:01...), 125),
  (datetime(...12:30:02...), 0),
]
```

Important planner assumptions:

- the CSV is already sorted by time
- there are no duplicate timestamps
- only `datetime` and `requests` matter
- missing seconds are filled with `0`

This timeline is the canonical script plan.

## Scheduler And Dispatcher

There are two separate concepts:

### Scheduler

The scheduler walks the timeline second by second.

For each item:

```python
(timestamp, request_count)
```

it waits until that scripted second arrives in the run, then hands the work to the dispatcher.

The scheduler is also responsible for:

- writing `locust_run_metadata.csv`
- logging progress every second
- periodic flushing of `locust_request_report.csv`

### Dispatcher

The dispatcher turns one second of planned load into many request jobs.

Current behavior:

- `burst` mode:
  - enqueue all requests for that second immediately
- `spread` mode:
  - spread enqueues across the second using evenly spaced offsets

So the scheduler decides:

- when a second starts

The dispatcher decides:

- how requests inside that second are paced

## Current Request Execution Model

Originally, each request used its own new `gevent.spawn_later(...)` greenlet. That was simple but expensive at high RPS.

The current design is cheaper:

- one fixed worker pool
- one shared queue
- the scheduler enqueues request jobs
- each worker takes a job, sends one request, waits for it to complete, then takes the next job

This is the key concurrency model:

- `SCRIPT_CONCURRENCY` controls the number of worker lanes
- each lane can have one active request in progress at a time
- if all workers are busy, new jobs stay queued

Very roughly:

```text
needed concurrency ~= target RPS * average response time in seconds
```

Example:

- target `1200 RPS`
- average response time `0.4s`
- rough needed concurrency `480`

If response time grows, needed concurrency grows too.

## What `workload.py` Does

`workload.py` decides what request gets sent.

It contains request builders such as:

- `range_prime_request`
- `kth_prime_request`
- `check_prime_request`
- `analyze_text_request`
- `transform_text_request`

The scheduler chooses an operation from the prebuilt operation cycle, then the worker executes it using Locust’s client. This keeps requests inside Locust’s own stats/event system.

## Locust-Side Verification

Locust writes `shares/locust_request_report.csv` with:

```csv
second,url,count
```

Important meaning:

- the count is recorded at request start
- this is best interpreted as:
  - "how many request attempts Locust started in that second"

This is not kernel-level wire truth, but it is a good application-level send-attempt metric.

Locust also writes `shares/locust_run_metadata.csv` with:

- `run_start_time`
- `run_start_second`
- script metadata such as duration and planned requests

This metadata is used to align ingress wall-clock timestamps to run-relative time.

## Ingress-Side Verification

Ingress verification is separate from Locust verification.

The raw ingress log is:

- `shares/ingress_raw.log`

The summarized ingress report is:

- `shares/ingress_request_report.csv`

The summarizer groups ingress arrivals by actual ingress wall-clock second.

This is important because ingress is the "truth at the gate":

- Locust tells us what it tried to send
- ingress tells us what actually arrived

## Canonical Comparison Strategy

There are two possible axes:

1. absolute wall-clock time
2. relative second into the run

The most useful comparison axis for the thesis is:

- relative second into the run

Recommended interpretation:

- `test_request`
  - planned by script second position
- `locust_request`
  - send attempts by Locust
- `ingress_request`
  - arrivals at ingress

To preserve network latency effects, ingress should not be forcibly relabeled to Locust’s internal script second. Instead:

- keep ingress timestamps real
- use `locust_run_metadata.csv` to convert ingress timestamps to relative run position in the notebook

This preserves natural drift and second-boundary spillover.

## Why The 1-Second Curves Can Look Milder

A major lesson from the experiments:

- the 5-second resampled curves matched much better than the 1-second curves

This strongly suggests much of the mismatch is due to in-second boundary effects rather than total-volume failure.

Typical causes:

- run starts in the middle of a wall-clock second
- `spread` mode distributes requests across a second
- requests near a boundary spill into neighboring seconds
- ingress reflects real arrival time, not plan time

So a 1-second chart can look noisier or "milder" even when total throughput is actually close.

## Progress Counters

Current progress logs include:

- `planned_requests`
  - script target for the current second
- `dispatched_so_far`
  - jobs enqueued by the scheduler
- `started`
  - requests that actually began execution in a worker
- `completed`
  - requests that returned successfully
- `failed`
  - requests that errored or returned `>= 400`

Useful interpretations:

- `dispatched_so_far - started`
  - queue backlog inside Locust
- `started - completed - failed`
  - in-flight requests still waiting on server/network

This split helps distinguish:

- scheduler cannot enqueue fast enough
- workers cannot start fast enough
- server path cannot complete fast enough

## Performance Bottlenecks We Identified

The original script-mode bottlenecks were:

1. one new greenlet per request
2. heavier `HttpSession` path
3. extra Python work per request
   - UUID creation
   - large custom headers
   - more logging work
4. waiting for server responses with too little concurrency

Improvements applied:

1. switched to `FastHttpSession`
2. replaced per-request greenlet creation with a reusable worker pool + queue
3. removed unnecessary custom request metadata headers
4. kept request logging minimal and at request start

These changes significantly reduce generator overhead.

## About Waiting For The Server

This is the most important concurrency insight.

Each worker currently does:

1. take one job
2. start one HTTP request
3. wait for the HTTP request to return
4. then take the next job

So yes:

- a worker is occupied until the server responds or the request errors/times out

That means response time matters directly to generator capacity.

If requests take longer, more workers are needed to maintain the same RPS.

## About "Not Waiting For Server To Finish"

We discussed two layers:

### Safe optimization

The safe idea was:

- do not eagerly consume the response body
- reduce client-side work after response headers arrive

This can reduce client overhead while still keeping normal HTTP semantics.

### Unsafe / conceptually different idea

A more extreme idea would be:

- fire-and-forget without completing the normal HTTP response cycle

That is not recommended for this use case because it changes the meaning of the test:

- requests may disconnect early
- ingress/server behavior may be distorted
- it stops looking like normal HTTP client traffic

So the safe path is acceptable for experiments, but true non-waiting would no longer be a normal Locust HTTP test.

## Full Response Removal Experiment

We also tried the more extreme experiment:

- completely remove response waiting
- treat a request as "done" as soon as the client writes the request bytes

The implementation replaced the pooled HTTP client with a raw socket send-only path.

What happened:

- each request opened a brand-new socket
- each request did a brand-new TCP connect
- request bytes were written once
- the socket was closed immediately
- no connection reuse remained

This introduced a worse bottleneck:

- connection churn
- repeated TCP setup cost
- much heavier pressure on the network stack
- likely more stress from ephemeral ports, connection teardown, and ingress accept behavior

The result was not better throughput. It trailed off harder and even produced transport-level errors such as:

- `OSError: [Errno 101] Network is unreachable`

So the experiment showed that removing response waiting in a naive raw-socket way does not solve the problem. It simply replaces one bottleneck with another, often worse one.

The better design is:

- keep connection reuse
- keep the efficient pooled HTTP transport
- reduce unnecessary response-body handling if needed

That is why the branch was moved back toward the pooled `FastHttpSession` path rather than keeping the raw send-only socket approach.

## Response-Time Coupling

Another important conclusion is that request throughput can become limited by the response time of the server.

In the current worker-pool design:

- one worker starts one request
- that worker stays occupied until the request completes
- only then can it pull another queued job

So if server responses slow down:

- more workers remain occupied
- fewer workers are available for new requests
- the queue grows
- Locust can drift away from the intended script shape

This means the request generator is not perfectly open-loop under heavy load. It becomes coupled to server response time.

The practical implication is:

- if response time is high enough, the load test may fail to reproduce the intended request shape exactly

This is not necessarily a flaw in the thesis, as long as the deviation is measured explicitly and reported honestly.

The defense is:

- the CSV defines the target demand shape
- Locust is the mechanism used to approximate that shape
- when the generated shape deviates, the mismatch is itself an experimental result
- the comparison between script, Locust, and ingress makes that deviation observable

## Distributed Locust

We also discussed master/worker architecture.

Conclusion:

- distributed Locust can help if one generator process is the bottleneck
- but it is not plug-and-play for this custom scheduler

Why:

- if every worker ran the full script independently, total load would be multiplied incorrectly

So distributed mode only helps if the scheduler becomes worker-aware and splits the planned load across workers correctly.

For now, the simpler path is:

- optimize the single-process generator first
- only move to distributed mode if Locust is still the limiting factor

## Practical Verification Summary

The verification story is now:

1. script CSV:
   - what should happen
2. Locust request report:
   - what Locust started sending
3. ingress request report:
   - what ingress actually received

And the notebook comparison should keep in mind:

- 1-second mismatch is often normal because of boundary effects
- 5-second resampling can reveal whether the true shape is actually close
- `started`, `completed`, and `failed` tell us whether the generator or the server path is falling behind

## Current State

At the current state of the branch:

- script mode uses a CSV-driven scheduler
- request generation is queue + worker based
- Locust uses `FastHttpSession`
- Locust writes:
  - `shares/locust_request_report.csv`
  - `shares/locust_run_metadata.csv`
- ingress writes:
  - `shares/ingress_raw.log`
  - `shares/ingress_request_report.csv`

This gives a workable setup for:

- scripted request generation
- run-relative comparison
- ingress-based verification
- diagnosing whether mismatch comes from scheduling, queueing, or server response time

## Remaining Pathways

At this point, the Locust test design is in a good state and the remaining bottleneck question has been narrowed down to two practical paths:

1. Increase concurrency
   - Keep the current Locust architecture
   - Raise `SCRIPT_CONCURRENCY`
   - Check whether the gap between `dispatched` and `started` shrinks
   - This is the cleaner path if the issue is simply too few in-flight slots

2. Remove response waiting
   - Move closer to a pure request sender rather than a normal Locust HTTP-response model
   - This would test whether server-response waiting is the dominant limiter
   - This is more experimental and changes the meaning of the load generator

These two paths are now the main unresolved branch point for further exploration.

## Status

This phase is considered done.

What has been achieved:

- a CSV-driven scripted Locust architecture
- a clear planner / scheduler / dispatcher split
- Locust-side and ingress-side verification
- run metadata for wall-clock alignment
- better progress counters for diagnosing bottlenecks
- a narrowed performance diagnosis centered on concurrency saturation vs response waiting

This provides a solid stopping point before moving on to the next problem.
