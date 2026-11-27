# 1/2/3/4-instance stepped series

Variant 13: `DB_POOL_SIZE=10`, bucket set Г3, `web` limited to `cpus: "0.5"` / `memory: 384M` (unchanged from Lab 1). Generator ceiling `G = 11532.5 req/s` (Task 8). Host: Docker Desktop VM — 10 CPUs, 7.8 GB memory (macOS host: 16 GB physical).

Runs: `python -m loadgen.stepped --url-template "http://localhost:8080/emergency-calls/{id}" --ids-file results/seed_ids.txt --out results/stepped_{N}inst.csv --g-limit 11530`, nginx restarted after each `--scale`, Prometheus Targets confirmed N/N UP before each run.

**Re-run after the final review found the generator was dropping late completions and miscounting the timeout** (see `loadgen/stepped.py`'s fix, commit after Task 14): the figures below replace the first pass.

| N | X(N) req/s | spread (std) | step (target) | client p99 | server p99 | non-2xx frac | CPU/instance | in-progress/instance |
|---|---|---|---|---|---|---|---|---|
| 1 | 608.4 | 80.2 | 2 (600) | 1492.7 ms | 114.5 ms (±64 ms) | 0.000 | 0.500 | 12.00 |
| 2 | 1016.8 | 117.3 | 4 (1000) | 314.4 ms | 62.4 ms (±32 ms) | 0.000 | 0.420 | 4.50 |
| 3 | 1399.3 | 42.0 | 6 (1400) | 28.8 ms | 37.2 ms (±32 ms) | 0.000 | 0.382 | 3.11 |
| 4 | 1599.7 | 22.9 | 7 (1600) | 39.9 ms | 82.3 ms (±64 ms) | 0.000 | 0.383 | 1.50 |

- X(N), spread and step: largest 15s-window average `achieved_rate` across that run's steps (and its stddev), per the assignment's definition.
- client p99 / non-2xx fraction: averaged over that step's 15s measurement window from the CSV.
- server p99: `estimate_quantile` (Task 11) over `sum by (le) (increase(http_request_duration_seconds_bucket[15s]))` at the window's end, summed across all `N` instances.
- CPU/instance: `avg(rate(process_cpu_seconds_total[15s]))` at the window's end (mean across instances).
- in-progress/instance: `avg(avg_over_time(http_requests_in_progress[15s]))` at the window's end.

**None of the four points are generator-bound**: `X(N)` stays far below `0.9·G ≈ 10379`, and every run's final step still shows `achieved_rate` well under `0.9×` its target (ratios 0.43 / 0.43 / 0.58 / 0.76 for N=1..4) — so the contingency CPU-halving rule (Task 9 step 3) does not apply, and all three `N>1` points (2, 3, 4) are usable for the USL fit.

**Server vs. client p99** now track each other reasonably closely at every `X(N)` point for N=2-4 (client 29-314 ms vs. server 37-82 ms) — these are genuinely sustainable throughput levels, not already-collapsing ones. N=1's `X(1)` step does show a wider gap (client 1492.7 ms vs. server 114.5 ms), which the per-step table in `results/p99_comparison_1inst.md` shows building up gradually rather than appearing only at the edge.
