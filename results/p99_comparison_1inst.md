# Client vs. server p99 — 1-instance run (`results/stepped_1inst.csv`)

Server p99 is the histogram-quantile estimate (`analysis/quantile.estimate_quantile`,
rank-interpolation per the assignment's Q(q) formula) over
`sum by (le) (increase(http_request_duration_seconds_bucket[15s]))` at
each step's 15s measurement window, bucket set Г3. Client p99 is the
15s-window average of the CSV's per-second `p99_ms`.

| step | target (req/s) | client p99 | server p99 | bucket it falls in | max estimation error |
|---|---|---|---|---|---|
| 0 | 200 | 29.0 ms | 25.5 ms | (16, 32] ms | ±16 ms |
| 1 | 400 | 44.3 ms | 20.3 ms | (16, 32] ms | ±16 ms |
| 2 | 600 | 33.9 ms | 24.8 ms | (16, 32] ms | ±16 ms |
| 3 | 800 | 2949.2 ms | 202.2 ms | (128, 256] ms | ±128 ms |
| 4 | 1000 | 7306.7 ms | 123.4 ms | (64, 128] ms | ±64 ms |

At 200-600 req/s client and server p99 track each other closely (both
under ~45ms) — negligible queueing outside the handler. From 800 req/s
on, server p99 stays under ~200ms while client p99 explodes into
multi-second territory: the single 0.5-CPU instance's own request
*handling* time barely changes, but requests queue for a long time
*before* being handled (CPU scheduling contention and/or waiting on the
10-connection DB pool) — the gap between client and server p99 is a
direct measurement of that queueing delay.
