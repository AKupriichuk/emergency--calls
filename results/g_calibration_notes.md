# Generator ceiling (G) calibration

Run: `python -m loadgen.stepped --url-template "http://localhost:8080/noop" --ids-file results/seed_ids.txt --out results/g_calibration.csv` (no `--g-limit`), against nginx's `/noop` (204, never reaches `web`), on a 10-core host.

- 59 steps ran (warmup@200, then 200..11800 req/s in +200 increments) before the two-consecutive-shortfall rule stopped it.
- Achieved rate tracked target almost exactly through target=11400 (step 56: 15s-window average achieved = **11532.5 req/s**, std = 431.3 — the largest average achieved rate across the whole run).
- At target=11600 p50 latency jumps from ~1ms to hundreds of ms and keeps climbing; at target=11800 latency explodes past 17s and achieved rate collapses to near 0 for most of the step — the load generator's own 10 worker processes / thread pools saturating, not nginx or the network (the endpoint is a static 204 with no backend call).

**G = 11532.5 req/s** (rounded for use as `--g-limit`: 11530).
