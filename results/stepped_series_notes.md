# 1/2/3/4-instance stepped series

Variant 13: `DB_POOL_SIZE=10`, bucket set Г3, `web` limited to `cpus: "0.5"` / `memory: 384M` (unchanged from Lab 1). Generator ceiling `G = 11532.5 req/s` (Task 8). Host: Docker Desktop VM — 10 CPUs, 7.8 GB memory (macOS host: 16 GB physical).

Runs: `python -m loadgen.stepped --url-template "http://localhost:8080/emergency-calls/{id}" --ids-file results/seed_ids.txt --out results/stepped_{N}inst.csv --g-limit 11530`, nginx restarted after each `--scale`, Prometheus Targets confirmed N/N UP before each run.

| N | X(N) req/s | spread (std) | step (target) | client p99 | server p99 | non-2xx frac | CPU/instance | in-progress/instance |
|---|---|---|---|---|---|---|---|---|
| 1 | 600.1 | 8.0 | 3 (600) | 33.9 ms | 24.8 ms (±16 ms) | 0.000 | 0.468 | 3.00 |
| 2 | 966.3 | 80.5 | 6 (1200) | 4940.8 ms | 120.6 ms (±64 ms) | 0.000 | 0.499 | 12.00 |
| 3 | 1238.8 | 122.4 | 7 (1400) | 2026.7 ms | 118.5 ms (±64 ms) | 0.000 | 0.496 | 7.22 |
| 4 | 1358.7 | 122.9 | 8 (1600) | 4582.7 ms | 124.5 ms (±64 ms) | 0.000 | 0.495 | 9.17 |

- X(N), spread and step: largest 15s-window average `achieved_rate` across that run's steps (and its stddev), per the assignment's definition.
- client p99 / non-2xx fraction: averaged over that step's 15s measurement window from the CSV.
- server p99: `estimate_quantile` (Task 11) over `sum by (le) (increase(http_request_duration_seconds_bucket[15s]))` at the window's end, summed across all `N` instances.
- CPU/instance: `avg(rate(process_cpu_seconds_total[15s]))` at the window's end (mean across instances).
- in-progress/instance: `avg(avg_over_time(http_requests_in_progress[15s]))` at the window's end.

**None of the four points are generator-bound**: `X(N)` stays far below `0.9·G ≈ 10379`, and every run's final step still shows `achieved_rate` well under `0.9×` its target (i.e. each run stopped on genuine saturation, not on hitting the generator's own ceiling) — so the contingency CPU-halving rule (Task 9 step 3) does not apply, and all three `N>1` points (2, 3, 4) are usable for the USL fit.

**Server vs. client p99 diverge sharply** from N=2 onward (server stays ≤125 ms while client reaches multi-second territory) — server-side handler latency is not the bottleneck; something outside the measured request-handling path (CPU scheduling under the 0.5-core limit, and/or DB-pool queueing against `DB_POOL_SIZE=10`, consistent with in-progress counts exceeding the pool size) is adding most of the client-observed latency. Followed up in Task 13.
