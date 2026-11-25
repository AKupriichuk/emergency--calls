"""Time-series charts combining a stepped-load run's CSV with Prometheus
data: target/achieved rate, client vs server p99, and per-instance
req/s + CPU + in-progress, all on one shared "seconds since run start"
axis.

The CSV only carries seconds relative to the run's own start, while
Prometheus range queries return absolute Unix timestamps, so the CLI
takes the run's own start time explicitly (--start) to align the two.
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import requests

from analysis.quantile import estimate_quantile
from analysis.scalability import usl_throughput

# Variant 13 bucket set Г3 (seconds), matching app/metrics.py's buckets.
_INF = float("inf")


def load_csv_rows(csv_path: str) -> list[dict]:
    with open(csv_path, newline="") as fh:
        return list(csv.DictReader(fh))


def query_range(prometheus_url: str, query: str, start: float, end: float, step: float) -> dict:
    response = requests.get(
        f"{prometheus_url}/api/v1/query_range",
        params={"query": query, "start": start, "end": end, "step": step},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def fetch_prometheus_data(prometheus_url: str, start: float, end: float) -> dict:
    """Pull every series plot_run needs from Prometheus for [start, end]."""
    return {
        "buckets": query_range(
            prometheus_url,
            "sum by (le) (increase(http_request_duration_seconds_bucket[15s]))",
            start, end, step=5,
        ),
        # A rate() window needs several scrape intervals' worth of samples
        # (Prometheus's scrape_interval here is 5s) or it comes back empty;
        # 15s matches the histogram query's own lookback above.
        "req_rate": query_range(
            prometheus_url, "sum by (instance) (rate(http_requests_total[15s]))", start, end, step=5,
        ),
        "cpu": query_range(
            prometheus_url, "rate(process_cpu_seconds_total[15s])", start, end, step=5,
        ),
        "in_progress": query_range(
            prometheus_url, "http_requests_in_progress", start, end, step=5,
        ),
    }


def _server_p99_series(buckets_result: dict, run_start: float) -> tuple[list[float], list[float | None]]:
    """(le -> cumulative count) per timestamp, reduced to a p99 estimate per timestamp."""
    by_time: dict[float, dict[float, float]] = defaultdict(dict)
    for series in buckets_result["data"]["result"]:
        le = series["metric"]["le"]
        le_value = _INF if le == "+Inf" else float(le)
        for ts, value in series["values"]:
            by_time[ts][le_value] = float(value)

    xs, ys = [], []
    for ts in sorted(by_time):
        le_map = by_time[ts]
        bounds = sorted(b for b in le_map if b != _INF)
        total = le_map.get(_INF, 0.0)
        bucket_list = [(b, le_map[b]) for b in bounds] + [(_INF, total)]
        estimate, _, exceeds = estimate_quantile(bucket_list, q=0.99)
        xs.append(ts - run_start)
        ys.append(None if exceeds else estimate * 1000)
    return xs, ys


def _instance_series(result: dict, run_start: float) -> dict[str, tuple[list[float], list[float]]]:
    series = {}
    for s in result["data"]["result"]:
        instance = s["metric"].get("instance", "?")
        xs = [ts - run_start for ts, _ in s["values"]]
        ys = [float(v) for _, v in s["values"]]
        series[instance] = (xs, ys)
    return series


def plot_run(csv_path: str, prometheus_range_json: dict, run_start: float, out_path: str) -> None:
    rows = load_csv_rows(csv_path)
    seconds = [int(r["second"]) for r in rows]
    target = [float(r["target_rate"]) for r in rows]
    achieved = [int(r["achieved_rate"]) for r in rows]
    client_p99 = [float(r["p99_ms"]) for r in rows]

    server_xs, server_p99 = _server_p99_series(prometheus_range_json["buckets"], run_start)
    req_rate_series = _instance_series(prometheus_range_json["req_rate"], run_start)
    cpu_series = _instance_series(prometheus_range_json["cpu"], run_start)
    in_progress_series = _instance_series(prometheus_range_json["in_progress"], run_start)

    fig, axes = plt.subplots(3, 1, figsize=(11, 10), sharex=True)

    axes[0].plot(seconds, target, label="target rate")
    axes[0].plot(seconds, achieved, label="achieved rate (2xx)")
    axes[0].set_ylabel("req/s")
    axes[0].set_title("Target vs. achieved rate")
    axes[0].legend()

    axes[1].plot(seconds, client_p99, label="client p99")
    axes[1].plot(server_xs, server_p99, label="server p99", marker=".", linestyle="")
    axes[1].set_ylabel("p99 latency (ms)")
    axes[1].set_title("Client vs. server p99")
    axes[1].legend()

    for instance, (xs, ys) in req_rate_series.items():
        axes[2].plot(xs, ys, label=f"{instance} req/s")
    for instance, (xs, ys) in cpu_series.items():
        axes[2].plot(xs, [y * 100 for y in ys], label=f"{instance} CPU %", linestyle="--")
    for instance, (xs, ys) in in_progress_series.items():
        axes[2].plot(xs, ys, label=f"{instance} in-progress", linestyle=":")
    axes[2].set_ylabel("per-instance req/s, CPU%, in-progress")
    axes[2].set_xlabel("seconds since run start")
    axes[2].set_title("Per-instance req/s, CPU usage, in-progress requests")
    axes[2].legend(fontsize="small", ncol=2)

    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def plot_usl_fit(
    points: list[tuple[int, float]],
    spreads: dict[int, float],
    lam: float,
    sigma: float,
    kappa: float,
    out_path: str,
) -> None:
    """Measured X(N) with error bars, the fitted USL curve, and the ideal
    linear-scaling line lambda*N, for N in 1..max(measured N)."""
    all_points = sorted({1: lam, **{n: x for n, x in points}}.items())
    ns = [n for n, _ in all_points]
    xs = [x for _, x in all_points]
    errs = [spreads.get(n, 0.0) for n in ns]

    curve_ns = list(range(1, max(ns) + 1))
    curve_xs = [usl_throughput(n, lam, sigma, kappa) for n in curve_ns]
    linear_xs = [lam * n for n in curve_ns]

    fig, ax = plt.subplots(figsize=(8, 6))
    ax.errorbar(ns, xs, yerr=errs, fmt="o", label="measured X(N)", capsize=4)
    ax.plot(curve_ns, curve_xs, label=f"USL fit (σ={sigma:.3f}, κ={kappa:.4f})")
    ax.plot(curve_ns, linear_xs, linestyle="--", label=f"ideal λN (λ={lam:.1f})")
    ax.set_xlabel("N (instances)")
    ax.set_ylabel("X(N) (req/s)")
    ax.set_title("Measured throughput vs. Universal Scalability Law fit")
    ax.set_xticks(curve_ns)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def _m3_throttle_fraction_by_time(
    prometheus_url: str, start: float, end: float
) -> dict[float, float]:
    """mean-across-instances throttled-period fraction per timestamp."""
    throttled = query_range(
        prometheus_url, "increase(cgroup_cpu_throttled_periods_total[15s])", start, end, step=5
    )
    periods = query_range(
        prometheus_url, "increase(cgroup_cpu_periods_total[15s])", start, end, step=5
    )

    def by_instance_time(result: dict) -> dict[str, dict[float, float]]:
        out: dict[str, dict[float, float]] = defaultdict(dict)
        for s in result["data"]["result"]:
            instance = s["metric"].get("instance", "?")
            for ts, v in s["values"]:
                out[instance][ts] = float(v)
        return out

    throttled_by = by_instance_time(throttled)
    periods_by = by_instance_time(periods)

    fractions_by_time: dict[float, list[float]] = defaultdict(list)
    for instance, periods_ts in periods_by.items():
        for ts, period_count in periods_ts.items():
            if period_count <= 0:
                continue
            throttled_count = throttled_by.get(instance, {}).get(ts, 0.0)
            fractions_by_time[ts].append(throttled_count / period_count)

    return {ts: sum(vals) / len(vals) for ts, vals in fractions_by_time.items() if vals}


def plot_m3_vs_rate(
    runs: list[tuple[int, str, str, float]], out_path: str
) -> None:
    """runs: list of (N, csv_path, prometheus_url, run_start)."""
    fig, ax = plt.subplots(figsize=(8, 6))
    for n, csv_path, prometheus_url, run_start in runs:
        rows = load_csv_rows(csv_path)
        duration_s = int(rows[-1]["second"]) + 1
        fractions_by_time = _m3_throttle_fraction_by_time(
            prometheus_url, run_start, run_start + duration_s
        )

        points = []
        for ts, frac in sorted(fractions_by_time.items()):
            offset = round(ts - run_start)
            if 0 <= offset < len(rows):
                target = float(rows[offset]["target_rate"])
                points.append((target, frac))
        points.sort()
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        ax.plot(xs, ys, marker=".", label=f"N={n}")

    ax.set_xlabel("target rate (req/s)")
    ax.set_ylabel("throttled fraction (nr_throttled / nr_periods)")
    ax.set_title("М3: CPU-throttled fraction vs. target intensity")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot a stepped run's time series against Prometheus data")
    parser.add_argument("--csv", required=True)
    parser.add_argument("--prometheus", required=True, help="Prometheus base URL, e.g. http://localhost:9090")
    parser.add_argument("--start", type=float, required=True, help="Run's own start time, Unix seconds")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    rows = load_csv_rows(args.csv)
    duration_s = int(rows[-1]["second"]) + 1
    prom_data = fetch_prometheus_data(args.prometheus, args.start, args.start + duration_s)
    plot_run(args.csv, prom_data, args.start, args.out)


if __name__ == "__main__":
    main()
