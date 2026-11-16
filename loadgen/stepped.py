"""Stepped-load profile: pure per-second aggregation and stop-rule logic.

Networking/execution glue that drives a live run lives in this module too
(added by the task that consumes these functions); this part has no I/O
so it can be unit-tested without a server or a clock.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from analysis.compute_metrics import _percentile


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
    rows: list[RequestResult], phase_start: float, duration_s: int, target_rate: float
) -> list[SecondSummary]:
    sent_buckets: list[list[RequestResult]] = [[] for _ in range(duration_s)]
    done_buckets: list[list[RequestResult]] = [[] for _ in range(duration_s)]

    for row in rows:
        sent_second = int(row.scheduled_ts - phase_start)
        if 0 <= sent_second < duration_s:
            sent_buckets[sent_second].append(row)
        done_second = int(row.done_ts - phase_start)
        if 0 <= done_second < duration_s:
            done_buckets[done_second].append(row)

    summaries = []
    for second in range(duration_s):
        done_rows = done_buckets[second]
        count_2xx = sum(1 for r in done_rows if 200 <= r.status_code < 300)
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
