# Add a k6 Exact-Script Runner While Keeping Locust

## Summary

Keep **Locust** for user-style / workflow-style generation, and add **k6** as a second runner dedicated to exact scripted request replay.

The external workflow stays stable:

- input stays `shares/test_script.csv`
- exact-script run still produces:
  - `shares/locust_request_report.csv`
  - `shares/locust_run_metadata.csv`
- ingress verification stays unchanged:
  - `shares/ingress_raw.log`
  - `shares/ingress_request_report.csv`

The main change is the underlying framework for the **exact-script** path: move that path from custom Locust scheduling to **k6 open-loop arrival-rate execution**.

## Key Changes

### 1. Keep Locust, add a separate k6 path

- Leave the current `locust` service and Locust files in place for user-generation experiments.
- Add a new `k6` Docker service and new make targets for exact-script replay.
- Do not reuse the `locust` command names for the new runner.
- Treat the existing Locust script-mode path as legacy/experimental, not the primary exact-replay path.

### 2. Preserve the current file contract

The new k6 path must preserve these interfaces:

- Input:
  - `shares/test_script.csv`
  - columns: `datetime`, `requests`
  - ignore `bandwidth`
- Output:
  - `shares/locust_request_report.csv`
    - schema: `second,url,count`
  - `shares/locust_run_metadata.csv`
    - keep the same schema currently used by the notebook

This keeps the notebook and downstream comparison flow stable.

### 3. Use k6 as the open-loop runner

Implement the exact-script path as a small wrapper pipeline around k6:

- A Python preprocessor reads `shares/test_script.csv`.
- It infers:
  - script start/end
  - total seconds
  - total planned requests
  - peak requests per second
- It writes `shares/locust_run_metadata.csv` before the run starts.
- It generates a k6 scenario file from the CSV.
- k6 runs in open-loop mode using arrival-rate executors.
- A Python postprocessor converts k6 raw metrics into `shares/locust_request_report.csv`.

### 4. Represent the CSV as k6 scenarios

Use **one k6 scenario per script second**.

For each second `t` with planned count `N`:

- create a `constant-arrival-rate` scenario
- `startTime = t seconds`
- `duration = 1s`
- `rate = N`
- `timeUnit = 1s`
- `exec` points to a one-request function

Reason for this choice:

- it preserves the per-second step shape directly
- it avoids Locust-style response-coupled scheduling
- it is more exact than using a ramping rate approximation

This is intentionally verbose but decision-safe for correctness.

### 5. Make one iteration equal one request

The k6 script should preserve the current workload semantics at a high level:

- one k6 iteration = one HTTP request
- keep the current weighted endpoint mix
- keep the current parameter ranges and request shapes
- keep the current prime/text weighting behavior

Implementation detail:

- generate or embed the same workload configuration semantics currently coming from env:
  - `PRIME_USER_WEIGHT`
  - `TEXT_USER_WEIGHT`
  - prime range/kth/check bounds
- per-iteration endpoint selection only needs to preserve the current weighted mix
- it does **not** need to preserve the exact same per-request sequence as Locust

### 6. Configure k6 for the intended open-loop behavior

Use these k6 behaviors by default:

- `discardResponseBodies: true`
- arrival-rate executors
- one-request iterations
- no extra sleeps

Expose VU sizing as env/config for the new runner:

- `K6_PREALLOCATED_VUS`
- `K6_MAX_VUS`

Default policy if unset:

- `preAllocatedVUs = peak_rps`
- `maxVUs = peak_rps * 2`

This is the chosen default for v1 because it is simple and tuned for exact replay rather than minimal resource usage.

### 7. Convert k6 raw output back into the current report

Do not rely on k6 summary output alone for the notebook report.

Instead:

- run k6 with raw CSV metric export to a temporary file in `shares/`
- postprocess that raw CSV into `shares/locust_request_report.csv`
- aggregate by:
  - second
  - URL
- count request starts using the k6 HTTP request metric stream

The postprocessor should only emit the final compact report file, not expose the raw k6 CSV as the primary artifact.

### 8. Enforce exactness with dropped-iteration detection

Because the goal is exact script replay, the wrapper should explicitly treat dropped iterations as failure.

Implementation behavior:

- parse k6 end-of-run summary or exported metrics
- if dropped iterations are nonzero:
  - mark the run failed
  - keep produced artifacts for diagnosis
  - print a clear message that the generator did not fully realize the intended script

This is the main correctness guard for the new exact-replay path.

### 9. Docker and command surface

Add a new `k6` service in `docker-compose.yml`:

- mount `./shares:/mnt/shares`
- no UI port required
- run as a one-shot script runner

Add new make targets:

- `build-k6`
- `run-k6-script`

Optional but acceptable if helpful:

- `k6-dry-run` for generating the scenario and metadata without running the test

Do not modify existing ingress log commands.

## Tests

### Functional scenarios

1. Small CSV smoke test
- 3 to 5 seconds
- mixed zero/nonzero rows
- verify generated k6 scenario count matches CSV seconds
- verify metadata file fields match the input script

2. Report compatibility test
- run against a reachable local target
- verify `shares/locust_request_report.csv` exists
- verify schema is exactly `second,url,count`
- verify `shares/locust_run_metadata.csv` matches the existing schema

3. Shape preservation test
- use a short script with visibly changing per-second counts
- verify the k6-side request report tracks the planned shape closely without the Locust-style response-coupled backlog behavior

4. Failure-mode test
- deliberately underprovision `K6_MAX_VUS`
- verify dropped iterations are detected
- verify the wrapper exits as failure with a clear message

5. Notebook compatibility test
- confirm the existing notebook can still load:
  - `shares/test_script.csv`
  - `shares/locust_request_report.csv`
  - `shares/locust_run_metadata.csv`
  - `shares/ingress_request_report.csv`
- no notebook code changes should be required for file names or schemas

## Assumptions And Defaults

- Keep both tools.
  - Locust stays for user/workflow generation.
  - k6 is added for exact-script replay.
- Keep the current file contract unchanged for the exact-script path.
- Preserve current workload semantics by weighted endpoint mix and parameter ranges, not exact per-request ordering.
- The new exact-script runner writes the final compact report after run completion; it does not need to preserve Locust’s minute-flush behavior in v1.
- The exact-script path should fail loudly when k6 drops iterations, because that means the intended shape was not fully reproduced.
