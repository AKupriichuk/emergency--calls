# Bottleneck diagnosis

**The shared resource that caps `X(N)` growth is the `web` container's `cpus: "0.5"` CPU limit** — not the database, not the host, and not the load generator.

Evidence, at the step where `X(4)=1358.7` req/s was reached (target=1600, `results/docker_stats_at_x4.txt`, snapshot at `2026-11-25T10:46:40Z`/`10:46:44Z`):

- All four `web` containers sit at **~48-52% CPU** (`docker stats`'s CPU% is a fraction of one whole host core, so this is the container fully consuming its 0.5-core quota — the cgroup limit, not a coincidence).
- `db` sits at only **~26-29% CPU** on the same snapshot — nowhere near saturated.
- `nginx` sits at **~15-20% CPU** — also far from saturated.
- The host (Docker Desktop VM) has **10 CPUs** total; with 4 web instances at 0.5 each that's 2 cores claimed out of 10 — host CPU itself has headroom too.
- The load generator's own ceiling (Task 8) is **G=11532.5 req/s**, nearly 8.5× the measured `X(4)=1358.7` — the generator is nowhere near its own limit at any of these throughput levels, ruling it out directly (a live `ps` snapshot of the generator process at the X(4) moment wasn't captured separately, but G's huge margin over every measured X(N) already settles this without one).

**М3 (cgroup CPU throttling) confirms it directly**: `results/m3_throttling_vs_rate.png` shows the throttled-period fraction (`nr_throttled / nr_periods`) jumping from near 0 to 80-100% at almost exactly the target rate where each run's throughput plateaus — ~600 req/s for N=1 (matching `X(1)=600.1`) and ~1400 req/s for N=4 (just below `X(4)`'s step at target=1600). The CPU scheduler is actively throttling the `web` processes right where growth stops, for both N=1 and N=4.

**Server-side request latency stays flat while client latency explodes**: Task 9/11's data shows server p99 (actual handler processing time, from the Prometheus histogram) staying under ~125-200ms across every N and every load level, while client p99 reaches multi-second territory from moderate load onward (`results/stepped_series_notes.md`, `results/p99_comparison_1inst.md`). That gap is queueing *before* the CPU-starved event loop gets to run each request, not slow application logic or slow queries — exactly what CPU throttling produces (requests pile up waiting for CPU time slices that the cgroup limit withholds), as opposed to, say, a saturated `DB_POOL_SIZE=10` (which would show up as slow *database* time inside the handler, raising server p99 too, not just client-observed queueing).

**Conclusion**: raising `X(N)` further requires raising the `web` container's CPU limit (or spreading the same total CPU budget across more, smaller instances won't help once host CPU itself becomes the constraint — at N=4 the system is still well short of that, since 4×0.5=2 cores out of 10 are in use). The database and the generator are not limiting factors at any of the measured points.
