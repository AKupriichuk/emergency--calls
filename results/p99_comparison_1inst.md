# Client vs. server p99 — 1-instance run (`results/stepped_1inst.csv`)

Re-run after the final review's generator fix (see `results/stepped_series_notes.md`).

Server p99 is the histogram-quantile estimate (`analysis/quantile.estimate_quantile`,
rank-interpolation per the assignment's Q(q) formula) over
`sum by (le) (increase(http_request_duration_seconds_bucket[15s]))` at
each step's 15s measurement window, bucket set Г3. Client p99 is the
15s-window average of the CSV's per-second `p99_ms`.

| step | target (req/s) | client p99 | server p99 | bucket it falls in | max estimation error |
|---|---|---|---|---|---|
| 0 | 200 | 29.0 ms | 23.7 ms | (16, 32] ms | ±16 ms |
| 1 | 400 | 33.0 ms | 15.2 ms | (8, 16] ms | ±8 ms |
| 2 | 600 | 1492.7 ms | 114.5 ms | (64, 128] ms | ±64 ms |
| 3 | 800 | 1098.5 ms | 118.3 ms | (64, 128] ms | ±64 ms |
| 4 | 1000 | 2736.7 ms | 127.4 ms | (64, 128] ms | ±64 ms |

At 200-400 req/s client and server p99 track each other closely (both
under ~35ms) — negligible queueing outside the handler. From 600 req/s
on (the step where `X(1)=608.4` is reached), server p99 settles around
~115-130ms while client p99 reaches into the multi-second range: the
single 0.5-CPU instance's own request-*handling* time changes relatively
little past this point, but requests queue for a long time *before*
being handled — the gap between client and server p99 is a direct
measurement of that queueing delay.
