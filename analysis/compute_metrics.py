"""Compute percentiles, achieved rate and error rate from raw load-generator
CSVs, plus the three required calculations: speedup/Karp-Flatt, Little's
Law, and the open-vs-closed-loop comparison."""

from __future__ import annotations

import argparse
import csv
import statistics
from dataclasses import dataclass


@dataclass
class RunSummary:
    achieved_rate: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    error_rate: float
    count: int


def load_measured_rows(path: str) -> list[dict]:
    with open(path, newline="") as fh:
        rows = list(csv.DictReader(fh))
    return [r for r in rows if r.get("warmup", "0") == "0"]


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    k = (len(sorted_values) - 1) * (pct / 100)
    f = int(k)
    c = min(f + 1, len(sorted_values) - 1)
    if f == c:
        return sorted_values[f]
    return sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f)


def summarize_run(path: str, duration_s: float) -> RunSummary:
    rows = load_measured_rows(path)
    latencies_ms = sorted((float(r["done_ts"]) - float(r["sent_ts"])) * 1000 for r in rows)
    errors = sum(1 for r in rows if r["status_code"] not in {"200", "201", "204"})
    return RunSummary(
        achieved_rate=len(rows) / duration_s,
        p50_ms=_percentile(latencies_ms, 50),
        p95_ms=_percentile(latencies_ms, 95),
        p99_ms=_percentile(latencies_ms, 99),
        error_rate=(errors / len(rows)) if rows else 0.0,
        count=len(rows),
    )


def median_of_repeats(paths: list[str], duration_s: float) -> RunSummary:
    summaries = [summarize_run(p, duration_s) for p in paths]
    return RunSummary(
        achieved_rate=statistics.median(s.achieved_rate for s in summaries),
        p50_ms=statistics.median(s.p50_ms for s in summaries),
        p95_ms=statistics.median(s.p95_ms for s in summaries),
        p99_ms=statistics.median(s.p99_ms for s in summaries),
        error_rate=statistics.median(s.error_rate for s in summaries),
        count=sorted(summaries, key=lambda s: s.achieved_rate)[len(summaries) // 2].count,
    )


def speedup_and_karp_flatt(throughput_1: float, throughput_2: float, n: int = 2) -> tuple[float, float]:
    s = throughput_2 / throughput_1
    e = (1 / s - 1 / n) / (1 - 1 / n)
    return s, e


def littles_law(path: str, duration_s: float) -> tuple[float, float, float, float, float]:
    """Compute the exact time-average number of in-flight requests via an
    event sweep (not a fixed-step grid sample): average latency here is a
    few tens of milliseconds, well under any grid step coarse enough to be
    fast, so grid sampling silently misses short in-flight intervals between
    samples and undercounts L. Sweeping the sorted +1/-1 events instead
    integrates the in-flight-count step function exactly."""
    rows = load_measured_rows(path)
    lam = len(rows) / duration_s
    w = statistics.mean(float(r["done_ts"]) - float(r["sent_ts"]) for r in rows)
    predicted_l = lam * w

    events: list[tuple[float, int]] = []
    for r in rows:
        events.append((float(r["sent_ts"]), 1))
        events.append((float(r["done_ts"]), -1))
    events.sort(key=lambda e: e[0])

    in_flight = 0
    area = 0.0
    prev_t = events[0][0]
    for t, delta in events:
        area += in_flight * (t - prev_t)
        in_flight += delta
        prev_t = t
    total_time = events[-1][0] - events[0][0]
    measured_l = area / total_time if total_time else 0.0

    discrepancy_pct = abs(measured_l - predicted_l) / measured_l * 100 if measured_l else 0.0
    return lam, w, predicted_l, measured_l, discrepancy_pct


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    summarize_p = sub.add_parser("summarize")
    summarize_p.add_argument("paths", nargs="+")
    summarize_p.add_argument("--duration", type=float, required=True)

    littles_p = sub.add_parser("littles-law")
    littles_p.add_argument("path")
    littles_p.add_argument("--duration", type=float, required=True)

    speedup_p = sub.add_parser("speedup")
    speedup_p.add_argument("--throughput1", type=float, required=True)
    speedup_p.add_argument("--throughput2", type=float, required=True)

    args = parser.parse_args()

    if args.cmd == "summarize":
        summary = median_of_repeats(args.paths, args.duration)
        print(summary)
    elif args.cmd == "littles-law":
        lam, w, predicted_l, measured_l, discrepancy = littles_law(args.path, args.duration)
        print(
            f"lambda={lam:.2f} req/s, W={w:.4f} s, L=lambda*W={predicted_l:.3f}, "
            f"measured L={measured_l:.3f}, discrepancy={discrepancy:.1f}%"
        )
    elif args.cmd == "speedup":
        s, e = speedup_and_karp_flatt(args.throughput1, args.throughput2)
        print(f"Speedup S={s:.3f}, Karp-Flatt e={e:.3f}")


if __name__ == "__main__":
    main()
