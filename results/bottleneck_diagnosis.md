# Bottleneck diagnosis

**The shared resource that caps `X(N)` growth is the `web` container's `cpus: "0.5"` CPU limit** — not the database, not the host, and not the load generator.

(Re-run after the final review's generator fix; see `results/stepped_series_notes.md`. The conclusion is unchanged — it rests on live container measurements, not on the generator's own bookkeeping.)

Evidence, at the step where `X(4)=1599.7` req/s was reached (target=1600, `results/docker_stats_at_x4.txt`, snapshot at `2026-11-25T13:08:14-18Z`):

- All four `web` containers sit at **~35-53% CPU** (`docker stats`'s CPU% is a fraction of one whole host core, so this is the container consuming close to its full 0.5-core quota — the cgroup limit, not a coincidence).
- `db` sits at only **~28-30% CPU** on the same snapshots — nowhere near saturated.
- `nginx` sits at **~20-22% CPU** — also far from saturated.
- The host (Docker Desktop VM) has **10 CPUs** total; with 4 web instances at 0.5 each that's 2 cores claimed out of 10 — host CPU itself has headroom too.
- The load generator's own ceiling (Task 8) is **G=11532.5 req/s**, over **7×** the measured `X(4)=1599.7`. This bounds the generator's raw *sending* capacity (measured against `/noop`, near-zero latency), which is a different limit from its per-worker thread-pool *concurrency* at higher per-request latency — but the client p99 actually measured at every `X(N)` point (29-1493 ms, `results/stepped_series_notes.md`) is well inside what that thread pool can sustain without itself becoming the constraint, so G's large margin still supports ruling the generator out at these specific throughput levels, just not as an unconditional proof at arbitrarily higher latency.

**М3 (cgroup CPU throttling) confirms it directly**: `results/m3_throttling_vs_rate.png` shows the throttled-period fraction (`nr_throttled / nr_periods`) jumping from near 0 to roughly 70-100% at almost exactly the target rate where each run's throughput plateaus — ~600 req/s for N=1 (matching `X(1)=608.4`) and ~1800-2000 req/s for N=4 (just past `X(4)=1599.7`'s own step). The CPU scheduler is actively throttling the `web` processes right where growth stops, for both N=1 and N=4.

**Server-side request latency stays comparatively flat while client latency diverges from N=1 onward**: `results/stepped_series_notes.md` and `results/p99_comparison_1inst.md` show server p99 (actual handler processing time, from the Prometheus histogram) staying in the tens-to-low-hundreds of milliseconds across every N and every load level, while client p99 at `X(1)` specifically reaches into the multi-second range (1492.7 ms) even though server p99 there is only 114.5 ms. That gap is queueing *before* the CPU-starved event loop gets to run each request. For N=2-4 the gap at each `X(N)` point is much narrower (client 29-314 ms vs. server 37-82 ms) — these three points are measured well before the onset of the same queueing effect, which is visible instead in those runs' later, post-peak steps.

**Conclusion**: raising `X(N)` further requires raising the `web` container's CPU limit — at N=4 the system is still well short of exhausting host CPU (4×0.5=2 cores out of 10 in use). The database is not a limiting factor at any of the measured points; the generator's large margin over every measured `X(N)` makes it an unlikely limiting factor too, though that margin narrows at higher per-request latency than anything observed here.
