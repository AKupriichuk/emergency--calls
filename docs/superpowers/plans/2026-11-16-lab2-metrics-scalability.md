# Lab 2 — Metrics and Scalability Limit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Instrument the emergency-calls service with Prometheus metrics, add
graceful shutdown, stand up Prometheus in Compose, build a stepped-load
generator, run the 1/2/3/4-instance series, and fit the Universal
Scalability Law to find the bottleneck — per variant 13 (`DB_POOL_SIZE=10`,
bucket set Г3, additional metric М3).

**Architecture:** Service gets a `prometheus_client` registry (counter,
histogram, gauge, plus a custom collector for the cgroup-throttling metric)
exposed at `GET /metrics`, a `/livez` probe, a `X-Pod` header, and a
shutdown hook that drains the DB pool on SIGTERM. Compose gains a
Prometheus server that discovers `web` replicas via `dns_sd_configs`. The
load generator gets a new stepped-profile mode that logs one row per
second (target/actual/achieved rate, 2xx/non-2xx/conn-error counts,
client p50/p95/p99) and stops itself on the rules in the assignment. Two
new `analysis/` modules do the histogram-quantile estimate and the USL
least-squares fit; both are pure functions over plain data, unit-tested
without any network or Docker dependency.

**Tech Stack:** FastAPI, `prometheus_client`, SQLAlchemy async (asyncpg),
Prometheus server, nginx, `matplotlib` for charts, `requests` for the
generator and for pulling data out of Prometheus's HTTP API.

**Spec:** `/Users/olexandra.kupriichuk/Downloads/умова-classroom.docx`
(Лабораторна робота 2) — full text already extracted earlier in this
conversation. Executors should ask the planner/session for the extracted
text if they need the exact Ukrainian wording; this plan carries every
value and formula they need to implement against.

## Global Constraints

- Variant 13: `DB_POOL_SIZE=10`, histogram bucket set Г3 (ms) =
  `1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024` → seconds =
  `0.001, 0.002, 0.004, 0.008, 0.016, 0.032, 0.064, 0.128, 0.256, 0.512, 1.024`.
  Additional metric М3: cgroup CPU throttling (`nr_periods`, `nr_throttled`
  from `/sys/fs/cgroup/cpu.stat`, cgroup v1 fallback
  `/sys/fs/cgroup/cpu,cpuacct/cpu.stat`), exposed as counters.
- `web` container CPU/memory limits stay exactly as in Lab 1:
  `cpus: "0.5"`, `memory: 384M` ([docker-compose.yml:43-46](../../../docker-compose.yml)). Do not change them
  except via the explicit halving contingency in Task 9.
- No literal config defaults in code for variant-controlled values
  (`DB_POOL_SIZE` included) — missing env var must fail startup, per the
  Lab 1 review fix already applied to `pagination_*` settings.
- Prometheus scrape interval: 5s. `dns_sd_configs` type `A`, port 8000,
  `refresh_interval: 5s`.
- Load profile: warmup 10s @ 200 req/s, then steps of 20s starting at
  200 req/s incrementing by 200 req/s. First 5s of every step is
  transient (excluded); the measured window is the last 15s.
- Achieved rate for a given second = count of **2xx** responses
  completed in that second (not all responses — this is the exact bug
  Lab 1's review flagged). Request timeout = 5s; a timeout counts as
  non-2xx.
- Client latency is measured from the **scheduled** send time, not the
  actual dispatch time.
- Stop rule for a stepped run: stop after a step if its 15s-window
  average achieved rate is `< 0.9 × target` for two consecutive steps,
  or if that average is `≥ G` (generator ceiling) when `G` is supplied.
- `X(N)` = largest 15s-window average achieved rate across the run's
  steps; its spread = stddev of per-second achieved rate over that same
  window.
- A point `N` is "generator-bound" if `X(N) ≥ 0.9·G` or the run's last
  step's achieved rate is `≥ 0.9 ×` its target; such points are excluded
  from the σ/κ fit.
- USL: `y(N) = N/C(N) − 1`, `u(N) = N−1`, `v(N) = N(N−1))`, least squares
  without intercept:
  `σ = (Σv²·Σuy − Σuv·Σvy) / (Σu²·Σv² − (Σuv)²)`,
  `κ = (Σu²·Σvy − Σuv·Σuy) / (Σu²·Σv² − (Σuv)²)`.
  If either comes out negative, clamp it to 0 and recompute the other
  single-parameter: `σ = Σuy/Σu²` (κ=0) or `κ = Σvy/Σv²` (σ=0).
  `N* = sqrt((1−σ)/κ)` when `κ>0 and σ<1`.
- Histogram quantile estimate: rank `r = q·n`; find bucket `i` with
  `c(i−1) < r ≤ c(i)`; `Q(q) = b(i−1) + (b(i)−b(i−1))·(r−c(i−1))/(c(i)−c(i−1))`,
  `b(0)=0, c(0)=0`; error bound = `b(i)−b(i−1)`; if `r` exceeds the last
  finite bucket, report `> b(k)` with an unbounded error.

## Review Focus

- **`pool_size`/`max_overflow` kwargs on a SQLite engine crash at import
  time** (`TypeError: Invalid argument(s) 'pool_size','max_overflow'`),
  confirmed by hand against `sqlite+aiosqlite:///:memory:` — the test
  suite imports `app.db` with that URL. Task 3 must guard these kwargs
  to the Postgres dialect only. Covered by Task 3's test.
- **`/metrics` must not 500 on a machine/container without the expected
  cgroup file** (local dev on macOS, or a cgroup layout that is neither
  v1 nor v2 at the documented paths). Covered by Task 2's test for a
  missing-file collector.
- **Achieved/target rate must count only 2xx, never all completed
  requests** — this is the literal Lab 1 review finding (comment 2/3).
  Covered by Task 6's aggregation tests using a mixed 2xx/5xx/timeout
  fixture.
- **Latency must use the scheduled send time, not the actual dispatch
  time** — easy to regress back to Lab 1's `sent_ts = time.time()`
  convention when reusing its generator code. Covered by Task 6/7 tests
  asserting latency is computed from `scheduled_ts`.
- **Scaling a Compose service doesn't change `nginx`'s or Prometheus's
  view of instances until they re-resolve DNS** — `nginx.conf` already
  re-resolves via `resolver ... valid=10s` with a `set $upstream` trick,
  but Prometheus's `dns_sd_configs` needs its own `refresh_interval: 5s`
  set explicitly (Task 5), and the experiment runbook (Task 9) must
  re-check the Targets page after every `--scale` before measuring.

---

## File Structure

- `app/metrics.py` — **create**. Prometheus registry: request counter,
  duration histogram (Г3 buckets), in-progress gauge, middleware that
  updates them, and the М3 cgroup-throttling custom collector.
- `app/main.py` — **modify**. Mount the metrics middleware, add
  `GET /metrics` and `GET /livez`, replace the `X-Instance-Id` header
  with `X-Pod` sourced from `POD_NAME` (fallback: hostname), add a
  shutdown hook that disposes the DB engine.
- `app/config.py` — **modify**. Add `db_pool_size: int` (required, no
  default) and `pod_name: str | None = None`.
- `app/db.py` — **modify**. Pass `pool_size`/`max_overflow=0` to
  `create_async_engine` only for the Postgres dialect.
- `requirements.txt` — **modify**. Add `prometheus-client==0.21.1`.
- `docker-compose.yml` — **modify**. Add `prometheus` service, named
  volume, published port; add `DB_POOL_SIZE` to `web`'s environment.
- `prometheus/prometheus.yml` — **create**. Scrape config with
  `dns_sd_configs` for `web`.
- `nginx/nginx.conf` — **modify**. Add `location = /noop { return 204; }`.
- `.env` / `.env.example` — **modify**. Add `DB_POOL_SIZE=10`.
- `loadgen/seed.py` — **modify**. Save all seeded ids (not just the
  first) to the output file, one per line.
- `loadgen/stepped.py` — **create**. Stepped-profile generator: pure
  aggregation/stop-decision functions plus the multiprocess execution
  glue and CLI.
- `analysis/quantile.py` — **create**. Histogram-quantile estimator
  (pure function) per the Q(q) formula above.
- `analysis/scalability.py` — **create**. USL σ/κ/N*/C(N) fit (pure
  function) per the formulas above.
- `analysis/plot_timeseries.py` — **create**. Matplotlib charts for
  Tasks 10 and 13, driven from Prometheus range-query JSON and generator
  CSVs.
- `requirements-dev.txt` — **modify**. Add `matplotlib==3.9.2`.
- `tests/test_metrics.py`, `tests/test_stepped_aggregation.py`,
  `tests/test_quantile.py`, `tests/test_scalability.py` — **create**.
- `README.md` — **modify**. Append Lab 2 stage sections, mirroring the
  Lab 1 reporting convention.

---

### Task 1: Core Prometheus metrics and `/metrics` endpoint

**Files:**
- Create: `app/metrics.py`
- Modify: `app/main.py`
- Modify: `requirements.txt`
- Test: `tests/test_metrics.py`

**Interfaces:**
- Produces: `app.metrics.setup_metrics(app: FastAPI) -> None` — registers
  the middleware and the `/metrics` route on the given app.
- Produces: module-level `REQUEST_COUNT` (Counter, labels `method`,
  `path`, `code`), `REQUEST_DURATION` (Histogram, labels `method`,
  `path`, buckets = the Г3 seconds list from Global Constraints),
  `REQUESTS_IN_PROGRESS` (Gauge, no labels).
- Consumes: nothing from other tasks.

- [ ] **Step 1: Write the failing test**

```python
def test_metrics_endpoint_reports_request_count_and_duration(client):
    client.get("/emergency-calls", params={"limit": 1})
    response = client.get("/metrics")
    assert response.status_code == 200
    body = response.text
    assert 'http_requests_total{code="200",method="GET",path="/emergency-calls"}' in body
    assert "http_request_duration_seconds_bucket" in body
    assert "http_requests_in_progress" in body
```

Use the path **template** (`/emergency-calls`, `/emergency-calls/{call_id}`
for the detail route), taken from `request.scope["route"].path`, never the
raw URL — otherwise every distinct id becomes its own series.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_metrics.py -v`
Expected: FAIL — no `/metrics` route yet.

- [ ] **Step 3: Implement `app/metrics.py` and wire it into `app/main.py`**

`setup_metrics` adds a `BaseHTTPMiddleware` that increments
`REQUESTS_IN_PROGRESS` on entry, decrements on exit (in a `finally`), and
on completion observes `REQUEST_DURATION` and increments
`REQUEST_COUNT` with the resolved route template, method, and status
code. The `/metrics` route returns
`Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)`
from `prometheus_client`. Call `setup_metrics(app)` in `app/main.py`
right after `app.include_router(router)`. Add
`prometheus-client==0.21.1` to `requirements.txt`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_metrics.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/metrics.py app/main.py requirements.txt tests/test_metrics.py
git commit -m "Add Prometheus request counter, duration histogram and in-progress gauge"
```

---

### Task 2: М3 — cgroup CPU-throttling metric

**Files:**
- Modify: `app/metrics.py`
- Test: `tests/test_metrics.py`

**Interfaces:**
- Produces: `parse_cpu_stat(text: str) -> dict[str, int]` — parses
  `key value` lines into a dict (pure, no I/O).
- Produces: `find_cpu_stat_path() -> str | None` — returns the first of
  `/sys/fs/cgroup/cpu.stat`, `/sys/fs/cgroup/cpu,cpuacct/cpu.stat` that
  exists and is readable, else `None`.
- Produces: `CgroupThrottleCollector` — a `prometheus_client` custom
  collector (`.collect()` yields `CounterMetricFamily` samples for
  `cgroup_cpu_periods_total` and `cgroup_cpu_throttled_periods_total`
  from the live file contents each scrape); yields nothing if
  `find_cpu_stat_path()` returns `None`. Registered once in
  `setup_metrics`.
- Consumes: Task 1's `setup_metrics`.

- [ ] **Step 1: Write the failing tests**

```python
def test_parse_cpu_stat_reads_periods_and_throttled():
    text = "nr_periods 120\nnr_throttled 4\nthrottled_usec 5000\n"
    assert parse_cpu_stat(text) == {"nr_periods": 120, "nr_throttled": 4, "throttled_usec": 5000}


def test_collector_yields_nothing_when_file_missing(monkeypatch):
    monkeypatch.setattr("app.metrics.find_cpu_stat_path", lambda: None)
    families = list(CgroupThrottleCollector().collect())
    assert families == []


def test_metrics_endpoint_survives_missing_cgroup_file(client, monkeypatch):
    monkeypatch.setattr("app.metrics.find_cpu_stat_path", lambda: None)
    response = client.get("/metrics")
    assert response.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_metrics.py -v`
Expected: FAIL — `parse_cpu_stat`/`CgroupThrottleCollector` undefined.

- [ ] **Step 3: Implement in `app/metrics.py`**

`find_cpu_stat_path` tries each path with `os.path.isfile` +
read-permission check (a bare `open(..).read()` inside a `try/except
OSError` is simplest — catch and move to the next candidate). The
collector's `.collect()` method must itself swallow `OSError` from a
file that existed at `find_cpu_stat_path()` time but became unreadable
by scrape time, and yield nothing rather than raising (this keeps the
Review Focus guarantee even under a race).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_metrics.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/metrics.py tests/test_metrics.py
git commit -m "Add М3 cgroup CPU-throttling collector with v1/v2 path fallback"
```

---

### Task 3: `/livez`, `X-Pod` header, `DB_POOL_SIZE` wiring

**Files:**
- Modify: `app/main.py`
- Modify: `app/config.py`
- Modify: `app/db.py`
- Modify: `.env`, `.env.example`
- Modify: `loadgen/generator.py` (rename `X-Instance-Id` → `X-Pod`)
- Test: `tests/test_validation.py` or a new `tests/test_ops.py`

**Interfaces:**
- Produces: `GET /livez` → 200, no DB access.
- Produces: every response header `X-Pod` = `settings.pod_name or
  socket.gethostname()`.
- Produces: `Settings.db_pool_size: int` (required), `Settings.pod_name:
  str | None = None`.
- Consumes: nothing from other tasks.

- [ ] **Step 1: Write the failing tests**

```python
def test_livez_does_not_touch_database(client, monkeypatch):
    # get_db override in conftest raises if called; livez must not depend on it
    response = client.get("/livez")
    assert response.status_code == 200


def test_response_carries_x_pod_header(client):
    response = client.get("/livez")
    assert "X-Pod" in response.headers
    assert response.headers["X-Pod"]  # non-empty; falls back to hostname
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ops.py -v`
Expected: FAIL — no `/livez` route, header still named `X-Instance-Id`.

- [ ] **Step 3: Implement**

`app/config.py`: add `db_pool_size: int` and `pod_name: str | None =
None` (the `None` default here is correct and intentional — the
assignment explicitly requires falling back to the hostname when
`POD_NAME` is unset, unlike the pagination case).

`app/main.py`: add `@app.get("/livez")` returning
`Response(status_code=200)` with no dependencies; rename the
`InstanceHeaderMiddleware` header to `X-Pod` and its value to
`get_settings().pod_name or socket.gethostname()`.

`app/db.py`: guard the pool kwargs by dialect —

```python
engine_kwargs = {"pool_pre_ping": True}
if settings.database_url.startswith("postgresql"):
    engine_kwargs["pool_size"] = settings.db_pool_size
    engine_kwargs["max_overflow"] = 0
engine = create_async_engine(settings.database_url, **engine_kwargs)
```

`.env`/`.env.example`: add `DB_POOL_SIZE=10`.

`loadgen/generator.py`: change `response.headers.get("X-Instance-Id",
"")` to `response.headers.get("X-Pod", "")`; the CSV column stays named
`instance_id` (it's the generator's own column name, not the header).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest -q`
Expected: all pass (existing + new).

- [ ] **Step 5: Commit**

```bash
git add app/main.py app/config.py app/db.py .env .env.example loadgen/generator.py tests/test_ops.py
git commit -m "Add /livez, X-Pod header, variant DB_POOL_SIZE wiring"
```

---

### Task 4: Graceful shutdown on SIGTERM

**Files:**
- Modify: `app/main.py`
- Test: manual (Docker-level; see verification step — this is not
  pytest-testable, the behavior under test is process signal handling)

**Interfaces:**
- Produces: a FastAPI shutdown event handler that calls
  `await engine.dispose()` (the engine from `app.db`).
- Consumes: Task 3's `app/db.py` engine.

- [ ] **Step 1: Implement the shutdown hook**

```python
@app.on_event("shutdown")
async def _dispose_engine() -> None:
    await engine.dispose()
```

Confirm `Dockerfile`'s `CMD` is already exec-form
(`CMD ["uvicorn", ...]`, [Dockerfile:15](../../../Dockerfile)) — it is, from the Lab 1 review fix pass;
no Dockerfile change needed here. Uvicorn's default signal handler
already stops accepting new connections and waits for in-flight ones on
SIGTERM; this task only adds the DB-pool cleanup the assignment
requires.

- [ ] **Step 2: Build the image and bring up a 2-replica stand**

Run:
```bash
docker compose up --build -d db migrate
docker compose up --build -d --scale web=2 web nginx
```

- [ ] **Step 3: Load the stand for 10s while stopping one replica mid-run**

Run a short open-loop run (existing `loadgen/generator.py open`) against
the published nginx port for ~10s, and in parallel
`docker stop <one web container>` a couple seconds in.

Expected: `docker inspect --format '{{.State.ExitCode}}' <container>` →
`0`; the generator's run shows **no** non-2xx responses and no
connection errors in the 10s window around the stop (the other replica
absorbs the traffic).

- [ ] **Step 4: Record the result**

Save the generator CSV and the `docker inspect` output under
`results/` for the Task 14 write-up (e.g.
`results/graceful_shutdown_2inst.csv`,
`results/graceful_shutdown_exitcode.txt`).

- [ ] **Step 5: Commit**

```bash
git add app/main.py results/graceful_shutdown_2inst.csv results/graceful_shutdown_exitcode.txt
git commit -m "Dispose DB engine on shutdown; verify SIGTERM drains in-flight requests"
```

---

### Task 5: Prometheus server in Compose, nginx `/noop`

**Files:**
- Modify: `docker-compose.yml`
- Create: `prometheus/prometheus.yml`
- Modify: `nginx/nginx.conf`

**Interfaces:**
- Produces: `prometheus` service reachable from the host, scraping
  `web` on port 8000 via `dns_sd_configs`.
- Produces: `GET /noop` on the nginx-published port → 204, no upstream
  call.
- Consumes: nothing from other tasks (infra-only).

- [ ] **Step 1: Write `prometheus/prometheus.yml`**

```yaml
global:
  scrape_interval: 5s
scrape_configs:
  - job_name: web
    dns_sd_configs:
      - names: ["web"]
        type: A
        port: 8000
        refresh_interval: 5s
```

- [ ] **Step 2: Add the `prometheus` service to `docker-compose.yml`**

```yaml
  prometheus:
    image: prom/prometheus:v2.55.1
    volumes:
      - ./prometheus/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - prometheus_data:/prometheus
    ports:
      - "9090:9090"
    depends_on:
      - web
```

Add `prometheus_data:` under the top-level `volumes:` key alongside
`pg_data:`. Add `DB_POOL_SIZE: ${DB_POOL_SIZE}` to `web`'s
`environment:` block.

- [ ] **Step 3: Add `/noop` to `nginx/nginx.conf`**

```nginx
    location = /noop {
        return 204;
    }
```

Inside the existing `server {}` block, alongside `location /`.

- [ ] **Step 4: Bring the stand up and verify Targets**

Run:
```bash
docker compose up --build -d
docker compose up -d --scale web=4
docker compose restart nginx
```

Open `http://localhost:9090/targets` (or
`curl -s localhost:9090/api/v1/targets | python3 -m json.tool`) and
confirm all 4 `web` instances show `health: "up"`.

Run: `curl -i http://localhost:8080/noop`
Expected: `204 No Content`, and `docker compose logs web` shows no new
request for `/noop`.

- [ ] **Step 5: Commit**

```bash
git add docker-compose.yml prometheus/prometheus.yml nginx/nginx.conf
git commit -m "Add Prometheus server with DNS service discovery and nginx /noop"
```

---

### Task 6: Stepped-load generator — pure aggregation and stop logic

**Files:**
- Create: `loadgen/stepped.py`
- Test: `tests/test_stepped_aggregation.py`

**Interfaces:**
- Produces: `RequestResult(scheduled_ts: float, done_ts: float,
  status_code: int, error: str)` dataclass.
- Produces: `SecondSummary(second: int, target_rate: float,
  actual_send_rate: int, achieved_rate: int, count_2xx: int,
  count_non_2xx: int, count_conn_errors: int, p50_ms: float,
  p95_ms: float, p99_ms: float)` dataclass.
- Produces: `aggregate_phase(rows: list[RequestResult], phase_start:
  float, duration_s: int, target_rate: float) -> list[SecondSummary]`.
- Produces: `window_average_achieved(summaries: list[SecondSummary],
  transient_s: float, window_s: float) -> tuple[float, float]` — returns
  `(mean, stddev)` of `achieved_rate` over the window
  `[transient_s, transient_s + window_s)`.
- Produces: `should_stop(step_avg_achieved: float, target_rate: float,
  g_limit: float | None, consecutive_below: int, ratio: float = 0.9) ->
  tuple[bool, int]` — returns `(stop, new_consecutive_below)`.
- Consumes: nothing from other tasks.

- [ ] **Step 1: Write the failing tests**

```python
def test_aggregate_phase_counts_only_2xx_as_achieved():
    rows = [
        RequestResult(scheduled_ts=0.2, done_ts=0.3, status_code=200, error=""),
        RequestResult(scheduled_ts=0.5, done_ts=0.6, status_code=502, error=""),
        RequestResult(scheduled_ts=0.7, done_ts=0.9, status_code=0, error="timeout"),
    ]
    summaries = aggregate_phase(rows, phase_start=0.0, duration_s=1, target_rate=3.0)
    assert summaries[0].achieved_rate == 1
    assert summaries[0].count_2xx == 1
    assert summaries[0].count_non_2xx == 2
    assert summaries[0].count_conn_errors == 0


def test_aggregate_phase_uses_scheduled_time_for_latency():
    rows = [RequestResult(scheduled_ts=10.0, done_ts=10.05, status_code=200, error="")]
    # dispatched late (actual send unknown/irrelevant here) but scheduled at t=10.0
    summaries = aggregate_phase(rows, phase_start=10.0, duration_s=1, target_rate=1.0)
    assert summaries[0].p50_ms == pytest.approx(50.0, abs=0.01)


def test_window_average_excludes_first_5s_of_a_20s_step():
    summaries = [
        SecondSummary(second=i, target_rate=200, actual_send_rate=200,
                       achieved_rate=(50 if i < 5 else 200), count_2xx=200,
                       count_non_2xx=0, count_conn_errors=0, p50_ms=1, p95_ms=1, p99_ms=1)
        for i in range(20)
    ]
    mean, _ = window_average_achieved(summaries, transient_s=5, window_s=15)
    assert mean == pytest.approx(200.0)


def test_should_stop_after_two_consecutive_shortfalls():
    stop, n = should_stop(step_avg_achieved=170, target_rate=200, g_limit=None, consecutive_below=0)
    assert (stop, n) == (False, 1)
    stop, n = should_stop(step_avg_achieved=170, target_rate=200, g_limit=None, consecutive_below=1)
    assert (stop, n) == (True, 2)


def test_should_stop_resets_counter_on_a_healthy_step():
    stop, n = should_stop(step_avg_achieved=200, target_rate=200, g_limit=None, consecutive_below=1)
    assert (stop, n) == (False, 0)


def test_should_stop_at_generator_ceiling():
    stop, n = should_stop(step_avg_achieved=5000, target_rate=5000, g_limit=4800, consecutive_below=0)
    assert stop is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_stepped_aggregation.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement `loadgen/stepped.py`'s pure functions**

`aggregate_phase` buckets rows by `int(done_ts - phase_start)` for the
response-side counts and `int(scheduled_ts - phase_start)` for
`actual_send_rate`; percentiles reuse the existing `_percentile` logic
style from `analysis/compute_metrics.py` (copy or import — your call,
but don't duplicate the formula silently differently). Latency for the
percentiles is always `(done_ts - scheduled_ts) * 1000`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_stepped_aggregation.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add loadgen/stepped.py tests/test_stepped_aggregation.py
git commit -m "Add pure per-second aggregation and stop-rule logic for stepped load profile"
```

---

### Task 7: Stepped-load generator — execution glue, CLI, seed update

**Files:**
- Modify: `loadgen/stepped.py`
- Modify: `loadgen/seed.py`

**Interfaces:**
- Produces: `run_phase(url_template: str, ids: list[str], rate: float,
  duration_s: float, start_time: float, timeout_s: float = 5.0) ->
  list[RequestResult]` — multiprocess send, same worker-process/thread-pool
  pattern as `loadgen/generator.py`'s `_open_loop_worker`, but each
  request targets `url_template.format(id=random.choice(ids))`, and
  `RequestResult.scheduled_ts` is the per-request target time (not
  `time.time()` at dispatch).
- Produces: `run_stepped(url_template: str, ids: list[str], out_path:
  str, g_limit: float | None) -> None` — drives warmup + steps using
  Task 6's `aggregate_phase`/`window_average_achieved`/`should_stop`,
  writes one `SecondSummary` row per second to `out_path` as it goes.
- Produces (CLI): `python -m loadgen.stepped --url-template
  "http://host:8080/emergency-calls/{id}" --ids-file results/seed_ids.txt
  --out results/stepped_1inst_run1.csv [--g-limit 1234.5]`.
- Consumes: Task 6's dataclasses and pure functions.

- [ ] **Step 1: Update `loadgen/seed.py` to save every id**

Change the output format from a single id to one id per line, and
rename the default `--out` to `results/seed_ids.txt`. Keep writing the
first id's line first so any Lab 1 script relying on "first line = an
id" still works unchanged.

- [ ] **Step 2: Implement `run_phase` and `run_stepped`**

Reuse the multiprocessing worker-pool shape from
`loadgen/generator.py:_open_loop_worker`/`run_open_loop`; the only
behavioral changes are: (a) each request's URL has a random id
substituted, (b) `RequestResult` carries `scheduled_ts` not an
after-the-fact `sent_ts`, (c) `run_stepped` is a loop over phases
(warmup, then steps with target rate `200*(i+1)`) that calls
`run_phase`, feeds the merged rows through `aggregate_phase`, appends
those `SecondSummary` rows to `out_path`, computes the window average,
calls `should_stop`, and either continues to the next step or returns.

- [ ] **Step 3: Smoke-test against the running Lab-1/2 stand**

Run:
```bash
docker compose up -d --scale web=1
python -m loadgen.stepped --url-template "http://localhost:8080/emergency-calls/{id}" \
  --ids-file results/seed_ids.txt --out results/stepped_smoke.csv
```

Expected: the file has header + one row per elapsed second, rates ramp
200→400→600→…, and the run stops itself once the server can't keep up
or a few steps have passed. Delete `results/stepped_smoke.csv`
afterward — it's a smoke check, not an experiment result.

- [ ] **Step 4: Commit**

```bash
git add loadgen/stepped.py loadgen/seed.py
git commit -m "Add stepped-load generator execution glue, CLI and multi-id seeding"
```

---

### Task 8: Generator ceiling (G) calibration run

**Files:**
- No new files — this is an experiment run using Task 7's CLI against
  Task 5's `/noop`.

**Interfaces:**
- Consumes: Task 7's `python -m loadgen.stepped` CLI, Task 5's `/noop`.
- Produces: `results/g_calibration.csv` and a recorded `G` value used by
  Task 9.

- [ ] **Step 1: Run the stepped profile against `/noop`, no `--g-limit`**

```bash
python -m loadgen.stepped --url-template "http://localhost:8080/noop" \
  --ids-file results/seed_ids.txt --out results/g_calibration.csv
```

(`/noop` ignores the `{id}` substitution — the URL template mechanism
from Task 7 still works since it never has a `{id}` placeholder here.)

- [ ] **Step 2: Compute G**

`G` = the largest `achieved_rate` 15s-window average across the run's
steps (same definition as `X(N)`, applied to this run). Record it in
`README.md`'s Lab 2 section (Task 14) and keep it at hand for Task 9.

- [ ] **Step 3: Commit**

```bash
git add results/g_calibration.csv
git commit -m "Record generator ceiling G from /noop calibration run"
```

---

### Task 9: 1/2/3/4-instance stepped series

**Files:**
- No new files — experiment runs using Task 7's CLI, recorded under
  `results/`.

**Interfaces:**
- Consumes: Task 7's CLI, Task 8's `G`, Task 5's Compose stand.
- Produces: `results/stepped_{N}inst.csv` for N in 1..4, plus a notes
  file with the per-N required readings.

- [ ] **Step 1: For each N in 1, 2, 3, 4 — scale, re-discover, run**

```bash
docker compose up -d --scale web=N
docker compose restart nginx
# confirm all N targets are "up" at http://localhost:9090/targets
python -m loadgen.stepped --url-template "http://localhost:8080/emergency-calls/{id}" \
  --ids-file results/seed_ids.txt --out results/stepped_{N}inst.csv --g-limit <G from Task 8>
```

- [ ] **Step 2: For each N, record the required readings**

From `results/stepped_{N}inst.csv`: `X(N)`, its spread, and which step
achieved it. For that step: client p99 (from the CSV), server p99 (from
Prometheus — see Task 11), non-2xx fraction, mean CPU per instance
(`process_cpu_seconds_total` rate from Prometheus), mean in-progress
requests per instance. Also record host/VM CPU count and memory (Docker
Desktop's VM settings, or `nproc`/`free -h` on a Linux host).

Write these into `results/stepped_series_notes.md` — one table, one row
per N.

- [ ] **Step 3: Apply the contingency rule if needed**

If `N=1` turned out generator-bound (per Global Constraints' rule), or
fewer than two `N>1` points are left for the fit, halve the `web`
container's CPU limit in `docker-compose.yml` (`cpus: "0.25"`), record
the new limit in `results/stepped_series_notes.md`, and repeat Step 1–2
for all four N again before moving on.

- [ ] **Step 4: Commit**

```bash
git add results/stepped_1inst.csv results/stepped_2inst.csv results/stepped_3inst.csv \
        results/stepped_4inst.csv results/stepped_series_notes.md docker-compose.yml
git commit -m "Run 1/2/3/4-instance stepped series and record required readings"
```

---

### Task 10: Time-series diagrams for 1 and 4 instances

**Files:**
- Create: `analysis/plot_timeseries.py`
- Modify: `requirements-dev.txt`

**Interfaces:**
- Produces: `plot_run(csv_path: str, prometheus_range_json: dict,
  out_path: str) -> None` — draws target/achieved rate, client vs
  server p99, and per-instance req/s + CPU + in-progress on a shared
  time axis; saves to `out_path` (PNG).
- Consumes: Task 9's `results/stepped_{1,4}inst.csv`; Prometheus's HTTP
  range-query API (`/api/v1/query_range`) for server p99 and per-instance
  series — pulled with `requests`, no new client library needed.

- [ ] **Step 1: Add `matplotlib==3.9.2` to `requirements-dev.txt`**

- [ ] **Step 2: Implement `plot_run`**

Three stacked subplots sharing the x-axis (seconds since run start):
(1) target vs achieved rate from the CSV; (2) client p99 (from the CSV)
vs server p99 (from a Prometheus range query — see Task 11's quantile
estimator, called per 5s step here with a 15s lookback window, matching
the assignment's "оновлення кожні 5 секунд"); (3) one line per instance
for req/s, CPU usage, and in-progress requests (three Prometheus range
queries, grouped by the `X-Pod`/instance label the metric carries).

- [ ] **Step 3: Generate both diagrams before tearing anything down**

```bash
python -m analysis.plot_timeseries --csv results/stepped_1inst.csv \
  --prometheus http://localhost:9090 --out results/timeseries_1inst.png
python -m analysis.plot_timeseries --csv results/stepped_4inst.csv \
  --prometheus http://localhost:9090 --out results/timeseries_4inst.png
```

Confirm both PNGs exist and look sane (axes labeled, data present)
**before** running `docker compose down -v` — Prometheus's data is in a
volume that this step needs intact.

- [ ] **Step 4: Commit**

```bash
git add analysis/plot_timeseries.py requirements-dev.txt \
        results/timeseries_1inst.png results/timeseries_4inst.png
git commit -m "Add Prometheus+CSV time-series charts for 1 and 4 instance runs"
```

---

### Task 11: Client-vs-server p99 comparison with bucket error bound

**Files:**
- Create: `analysis/quantile.py`
- Test: `tests/test_quantile.py`

**Interfaces:**
- Produces: `estimate_quantile(buckets: list[tuple[float, int]], q: float)
  -> tuple[float | None, float, bool]` — `buckets` is
  `[(upper_bound_seconds, cumulative_count), ...]` sorted ascending,
  last entry is `(float("inf"), total_count)`; returns `(estimate,
  error_bound, exceeds_last_finite_bucket)`. When the rank falls past
  the last finite bucket, `estimate=None` (caller renders `"> b(k)"`),
  `error_bound=float("inf")`, `exceeds_last_finite_bucket=True`.
- Consumes: nothing from other tasks (pure function); the CLI glue that
  pulls live bucket counts from Prometheus for each step of the
  1-instance run belongs in `analysis/plot_timeseries.py`'s CLI (Task
  10) or a small script reusing this function — your call, not a new
  task.

- [ ] **Step 1: Write the failing tests**

```python
def test_estimate_quantile_interpolates_within_a_bucket():
    # buckets in seconds, matching Г3 (ms->s): 0.001..1.024, +inf
    buckets = [(0.001, 0), (0.002, 0), (0.004, 2), (0.008, 10), (float("inf"), 10)]
    estimate, error_bound, exceeds = estimate_quantile(buckets, q=0.5)
    # n=10, r=5 -> falls in (0.004, 0.008] bucket: c(i-1)=2, c(i)=10
    assert estimate == pytest.approx(0.004 + (0.008 - 0.004) * (5 - 2) / (10 - 2))
    assert error_bound == pytest.approx(0.004)
    assert exceeds is False


def test_estimate_quantile_reports_overflow_past_last_finite_bucket():
    buckets = [(0.001, 0), (0.002, 1), (float("inf"), 10)]
    estimate, error_bound, exceeds = estimate_quantile(buckets, q=0.99)
    assert estimate is None
    assert error_bound == float("inf")
    assert exceeds is True


def test_estimate_quantile_handles_first_bucket():
    buckets = [(0.001, 3), (float("inf"), 3)]
    estimate, error_bound, exceeds = estimate_quantile(buckets, q=0.5)
    assert estimate == pytest.approx(0.001 * (1.5 - 0) / (3 - 0))
    assert error_bound == pytest.approx(0.001)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_quantile.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement `estimate_quantile`**

`b(0)=0, c(0)=0` per Global Constraints; rank `r = q * c(last finite
bucket's... )` — careful: `n` is the **total** observation count
(the last, `+inf`, bucket's cumulative count), not the last finite
bucket's count.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_quantile.py -v`
Expected: PASS

- [ ] **Step 5: Produce the per-step comparison table for the 1-instance run**

For each step of `results/stepped_1inst.csv`: client p99 (already in
the CSV) vs server p99 (query Prometheus's histogram bucket counters for
that step's time window, feed into `estimate_quantile`). Save as
`results/p99_comparison_1inst.md` (or `.csv` — pick one and be
consistent with the rest of `results/`).

- [ ] **Step 6: Commit**

```bash
git add analysis/quantile.py tests/test_quantile.py results/p99_comparison_1inst.md
git commit -m "Add histogram-quantile estimator and client-vs-server p99 comparison"
```

---

### Task 12: Universal Scalability Law fit

**Files:**
- Create: `analysis/scalability.py`
- Test: `tests/test_scalability.py`

**Interfaces:**
- Produces: `fit_usl(points: list[tuple[int, float]]) -> tuple[float,
  float]` — `points` is `[(N, X(N)), ...]` for `N > 1` only (the
  generator-bound `N=1` point, or any generator-bound point, is excluded
  by the **caller**, per Global Constraints — `fit_usl` itself just fits
  whatever points it's given); returns `(sigma, kappa)`, each clamped to
  `0` and refit single-parameter per the Global Constraints rule when
  negative.
- Produces: `usl_throughput(n: int, lam: float, sigma: float, kappa:
  float) -> float` — `X(N) = λN / (1 + σ(N−1) + κN(N−1))`.
- Produces: `optimal_n(sigma: float, kappa: float) -> float | None` —
  `sqrt((1-σ)/κ)` when `κ>0 and σ<1`, else `None`.
- Consumes: nothing from other tasks (pure function).

- [ ] **Step 1: Write the failing tests**

```python
def test_fit_usl_recovers_known_sigma_and_kappa():
    sigma, kappa = 0.05, 0.001
    lam = 500.0
    points = [(n, usl_throughput(n, lam, sigma, kappa)) for n in (2, 3, 4)]
    fitted_sigma, fitted_kappa = fit_usl(points)
    assert fitted_sigma == pytest.approx(sigma, abs=1e-6)
    assert fitted_kappa == pytest.approx(kappa, abs=1e-6)


def test_fit_usl_clamps_negative_sigma_to_zero():
    # kappa-only data: C(N) grows slower than 1/N would from sigma alone
    points = [(2, 480.0), (3, 420.0), (4, 300.0)]
    sigma, kappa = fit_usl(points)
    assert sigma >= 0
    assert kappa >= 0


def test_optimal_n_matches_formula():
    assert optimal_n(sigma=0.05, kappa=0.001) == pytest.approx(((1 - 0.05) / 0.001) ** 0.5)


def test_optimal_n_is_none_when_kappa_zero():
    assert optimal_n(sigma=0.05, kappa=0.0) is None
```

Note: `usl_throughput` must be implemented (or at least its formula
available) before writing `test_fit_usl_recovers_known_sigma_and_kappa`,
since the test uses it to build synthetic data — implement both
functions in Step 3 before running Step 2's "expect fail", or write
`usl_throughput` inline in the test file if you want Step 2 to fail only
on `fit_usl`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_scalability.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement `analysis/scalability.py`**

Follow the Global Constraints formulas exactly, including the
negative-coefficient clamp-and-refit rule.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_scalability.py -v`
Expected: PASS

- [ ] **Step 5: Run the fit on the real Task 9 data and chart it**

Using `results/stepped_series_notes.md`'s `X(N)` values (excluding any
generator-bound point), compute `σ, κ, N*, C(N)`, then plot measured
`X(N)` with its spread as error bars, the fitted USL curve, and the
`λN` line (`λ = X(1)`) on one chart — extend
`analysis/plot_timeseries.py` with a `plot_usl_fit(...)` function, or a
small standalone script; either is fine, but don't duplicate the fit
formulas outside `analysis/scalability.py`. Save as
`results/usl_fit.png`.

- [ ] **Step 6: Commit**

```bash
git add analysis/scalability.py tests/test_scalability.py results/usl_fit.png
git commit -m "Add USL least-squares fit and plot measured X(N) against it"
```

---

### Task 13: Bottleneck diagnosis and variant-metric diagram

**Files:**
- No new source files — uses Task 10's charting module and Task 9's
  stand (still up, at the `X(4)` step).
- Modify: `analysis/plot_timeseries.py` (add one more chart function if
  not already generic enough to reuse as-is).

**Interfaces:**
- Consumes: Task 2's М3 collector (already scraped by Prometheus since
  Task 5), Task 9's running stand.

- [ ] **Step 1: At the step where `X(4)` was achieved, capture container stats**

```bash
docker stats --no-stream > results/docker_stats_at_x4.txt
```

Also capture the generator process's own CPU/memory at that moment
(e.g. `ps -o %cpu,%mem -p <generator pid>` or the OS's process monitor),
appended to the same file.

- [ ] **Step 2: Chart the М3 metric vs target intensity for 1 and 4 instances**

Query Prometheus for `increase(cgroup_cpu_throttled_periods_total[…])
/ increase(cgroup_cpu_periods_total[…])` per instance, aligned to each
step's target rate from `results/stepped_{1,4}inst.csv`. Plot throttled
fraction (y) vs target rate (x), one line per instance count. Save as
`results/m3_throttling_vs_rate.png`.

- [ ] **Step 3: Write the bottleneck diagnosis**

Using `results/docker_stats_at_x4.txt`, the Prometheus
`process_cpu_seconds_total` rates, and `results/m3_throttling_vs_rate.png`,
identify the shared resource that caps `X(N)` growth (web CPU limit,
DB pool/DB CPU, host CPU, or the generator itself) — write this as a
paragraph into `results/bottleneck_diagnosis.md`, citing the specific
numbers that support the conclusion.

- [ ] **Step 4: Commit**

```bash
git add results/docker_stats_at_x4.txt results/m3_throttling_vs_rate.png results/bottleneck_diagnosis.md
git commit -m "Diagnose the shared-resource bottleneck using cgroup throttling and container stats"
```

---

### Task 14: Report write-up

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: every prior task's `results/*` artifacts and numbers.

- [ ] **Step 1: Append Lab 2 stage sections to `README.md`**

Mirror the Lab 1 convention exactly (`## Stage N — <title>`, filled in
as each task above lands, not rewritten after the fact): metrics
(Tasks 1–2), ops endpoints (Task 3), graceful shutdown (Task 4),
Compose/Prometheus (Task 5), generator (Tasks 6–7), G calibration
(Task 8), the four-instance series (Task 9), diagrams (Task 10), p99
comparison (Task 11), USL fit (Task 12), bottleneck diagnosis (Task 13),
plus "Rejected approaches", "Use of generative models", and "Control
questions" sections matching Lab 1's structure.

- [ ] **Step 2: Export to Word for submission**

Once the README sections are final, use the `docx` skill to produce
`Звіт_Лаб2_Метрики_Купрійчук.docx` the same way Lab 1's report was
produced, following this session's docx-authoring conventions (verify
by rendering to PDF/images before calling it done).

- [ ] **Step 3: Commit**

```bash
git add README.md Звіт_Лаб2_Метрики_Купрійчук.docx
git commit -m "Write Lab 2 report"
```
