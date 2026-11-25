"""Stepped-load profile: pure per-second aggregation and stop-rule logic.

Networking/execution glue that drives a live run lives in this module too
(added by the task that consumes these functions); this part has no I/O
so it can be unit-tested without a server or a clock.
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import multiprocessing as mp
import os
import random
import statistics
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import requests

from analysis.compute_metrics import _percentile

WARMUP_RATE = 200.0
WARMUP_DURATION_S = 10
STEP_DURATION_S = 20
STEP_INCREMENT = 200.0
TRANSIENT_S = 5.0
WINDOW_S = 15.0
TIMEOUT_S = 5.0


@dataclass
class RequestResult:
    scheduled_ts: float
    done_ts: float
    status_code: int
    error: str


@dataclass
class SecondSummary:
    second: int
    target_rate: float
    actual_send_rate: int
    achieved_rate: int
    count_2xx: int
    count_non_2xx: int
    count_conn_errors: int
    p50_ms: float
    p95_ms: float
    p99_ms: float


def aggregate_phase(
    rows: list[RequestResult],
    phase_start: float,
    duration_s: int,
    target_rate: float,
    timeout_s: float = 5.0,
) -> list[SecondSummary]:
    # A worker waits for every scheduled request to finish, however late, so
    # a result can legitimately complete after the phase's nominal duration
    # (queueing under overload). Size the bucket range to cover every actual
    # completion instead of silently discarding the stragglers.
    max_done_second = max((int(r.done_ts - phase_start) for r in rows), default=-1)
    span = max(duration_s, max_done_second + 1)

    sent_buckets: list[list[RequestResult]] = [[] for _ in range(span)]
    done_buckets: list[list[RequestResult]] = [[] for _ in range(span)]

    for row in rows:
        sent_second = int(row.scheduled_ts - phase_start)
        if 0 <= sent_second < span:
            sent_buckets[sent_second].append(row)
        done_second = int(row.done_ts - phase_start)
        if 0 <= done_second < span:
            done_buckets[done_second].append(row)

    summaries = []
    for second in range(span):
        done_rows = done_buckets[second]
        # A result that took longer than the timeout to complete (measured
        # from the scheduled send time) counts as non-2xx regardless of the
        # status code the late response actually carried.
        count_2xx = sum(
            1
            for r in done_rows
            if 200 <= r.status_code < 300 and (r.done_ts - r.scheduled_ts) <= timeout_s
        )
        # A timeout counts as non-2xx, not as a connection error (spec: "запит,
        # що перевищив тайм-аут, рахується як відповідь з кодом не 2xx").
        count_conn_errors = sum(1 for r in done_rows if r.error and "timeout" not in r.error.lower())
        count_non_2xx = len(done_rows) - count_2xx

        latencies_ms = sorted((r.done_ts - r.scheduled_ts) * 1000 for r in done_rows)
        summaries.append(
            SecondSummary(
                second=second,
                target_rate=target_rate,
                actual_send_rate=len(sent_buckets[second]),
                achieved_rate=count_2xx,
                count_2xx=count_2xx,
                count_non_2xx=count_non_2xx,
                count_conn_errors=count_conn_errors,
                p50_ms=_percentile(latencies_ms, 50),
                p95_ms=_percentile(latencies_ms, 95),
                p99_ms=_percentile(latencies_ms, 99),
            )
        )
    return summaries


def window_average_achieved(
    summaries: list[SecondSummary], transient_s: float, window_s: float
) -> tuple[float, float]:
    window = [
        s.achieved_rate for s in summaries if transient_s <= s.second < transient_s + window_s
    ]
    if not window:
        return 0.0, 0.0
    mean = statistics.mean(window)
    stddev = statistics.pstdev(window) if len(window) > 1 else 0.0
    return mean, stddev


def should_stop(
    step_avg_achieved: float,
    target_rate: float,
    g_limit: float | None,
    consecutive_below: int,
    ratio: float = 0.9,
) -> tuple[bool, int]:
    if g_limit is not None and step_avg_achieved >= g_limit:
        return True, consecutive_below

    if step_avg_achieved < ratio * target_rate:
        consecutive_below += 1
        return consecutive_below >= 2, consecutive_below

    return False, 0


def _do_stepped_request(
    session: requests.Session, url: str, timeout_s: float, target_time: float
) -> RequestResult:
    try:
        response = session.get(url, timeout=timeout_s)
        return RequestResult(target_time, time.time(), response.status_code, "")
    except requests.Timeout:
        return RequestResult(target_time, time.time(), 0, "timeout")
    except requests.RequestException as exc:
        return RequestResult(target_time, time.time(), 0, str(exc))


def _write_phase_part(path: str, results: list[RequestResult]) -> None:
    with open(path, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["scheduled_ts", "done_ts", "status_code", "error"])
        for r in results:
            writer.writerow([r.scheduled_ts, r.done_ts, r.status_code, r.error])


def _read_phase_part(path: str) -> list[RequestResult]:
    with open(path, newline="") as fh:
        return [
            RequestResult(
                float(row["scheduled_ts"]), float(row["done_ts"]), int(row["status_code"]), row["error"]
            )
            for row in csv.DictReader(fh)
        ]


def _phase_worker(
    url_template: str,
    ids: list[str],
    worker_rate: float,
    duration_s: float,
    start_time: float,
    timeout_s: float,
    out_path: str,
) -> None:
    session = requests.Session()
    count = max(1, int(worker_rate * duration_s))
    results: list[RequestResult] = []

    with ThreadPoolExecutor(max_workers=max(4, int(worker_rate / 5) + 1)) as pool:
        futures = []
        for seq in range(count):
            target_time = start_time + seq / worker_rate
            sleep_for = target_time - time.time()
            if sleep_for > 0:
                time.sleep(sleep_for)
            url = url_template.format(id=random.choice(ids))
            futures.append(pool.submit(_do_stepped_request, session, url, timeout_s, target_time))
        for future in futures:
            results.append(future.result())

    _write_phase_part(out_path, results)


def run_phase(
    url_template: str,
    ids: list[str],
    rate: float,
    duration_s: float,
    start_time: float,
    timeout_s: float = 5.0,
) -> list[RequestResult]:
    num_workers = os.cpu_count() or 1
    worker_rate = rate / num_workers

    with tempfile.TemporaryDirectory() as tmp_dir:
        part_paths = [os.path.join(tmp_dir, f"part{i}.csv") for i in range(num_workers)]
        processes = [
            mp.Process(
                target=_phase_worker,
                args=(url_template, ids, worker_rate, duration_s, start_time, timeout_s, part_paths[i]),
            )
            for i in range(num_workers)
        ]
        for p in processes:
            p.start()
        for p in processes:
            p.join()

        rows: list[RequestResult] = []
        for part_path in part_paths:
            rows.extend(_read_phase_part(part_path))
        return rows


def _append_summaries(out_path: str, summaries: list[SecondSummary], elapsed_s: int, write_header: bool) -> None:
    fieldnames = [f.name for f in dataclasses.fields(SecondSummary)]
    with open(out_path, "a", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        for s in summaries:
            row = dataclasses.asdict(s)
            row["second"] = elapsed_s + s.second
            writer.writerow(row)


def run_stepped(url_template: str, ids: list[str], out_path: str, g_limit: float | None) -> None:
    start_time = time.time() + 1.0
    elapsed = 0

    rows = run_phase(url_template, ids, WARMUP_RATE, WARMUP_DURATION_S, start_time, timeout_s=TIMEOUT_S)
    summaries = aggregate_phase(rows, start_time, WARMUP_DURATION_S, WARMUP_RATE, timeout_s=TIMEOUT_S)
    _append_summaries(out_path, summaries, elapsed, write_header=True)
    # Advance by however many seconds were actually written, not the nominal
    # duration -- a phase that overran (stragglers past its window) gets
    # extra summary rows, and the next phase's "second" column must start
    # right after the last one actually written, or two phases would claim
    # the same second.
    elapsed += len(summaries)

    consecutive_below = 0
    step_index = 0
    while True:
        target_rate = WARMUP_RATE + STEP_INCREMENT * step_index
        phase_start = start_time + elapsed
        rows = run_phase(url_template, ids, target_rate, STEP_DURATION_S, phase_start, timeout_s=TIMEOUT_S)
        summaries = aggregate_phase(rows, phase_start, STEP_DURATION_S, target_rate, timeout_s=TIMEOUT_S)
        _append_summaries(out_path, summaries, elapsed, write_header=False)
        elapsed += len(summaries)

        step_avg, _ = window_average_achieved(summaries, TRANSIENT_S, WINDOW_S)
        stop, consecutive_below = should_stop(step_avg, target_rate, g_limit, consecutive_below)
        step_index += 1
        if stop:
            return


def main() -> None:
    parser = argparse.ArgumentParser(description="Stepped-load profile generator")
    parser.add_argument("--url-template", required=True)
    parser.add_argument("--ids-file", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--g-limit", type=float, default=None)
    args = parser.parse_args()

    with open(args.ids_file) as fh:
        ids = [line.strip() for line in fh if line.strip()]

    run_stepped(args.url_template, ids, args.out, args.g_limit)


if __name__ == "__main__":
    main()
