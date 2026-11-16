"""Histogram-quantile estimate per the assignment's rank-interpolation
formula: Q(q) = b(i-1) + (b(i)-b(i-1)) * (r-c(i-1)) / (c(i)-c(i-1)),
with b(0)=0, c(0)=0, rank r = q*n, n = total observation count."""

from __future__ import annotations


def estimate_quantile(
    buckets: list[tuple[float, int]], q: float
) -> tuple[float | None, float, bool]:
    finite_buckets = buckets[:-1]
    total_count = buckets[-1][1]
    rank = q * total_count

    last_finite_count = finite_buckets[-1][1] if finite_buckets else 0
    if rank > last_finite_count:
        return None, float("inf"), True

    prev_bound = 0.0
    prev_count = 0.0
    for bound, count in finite_buckets:
        if prev_count < rank <= count:
            estimate = prev_bound + (bound - prev_bound) * (rank - prev_count) / (count - prev_count)
            error_bound = bound - prev_bound
            return estimate, error_bound, False
        prev_bound, prev_count = bound, count

    return None, float("inf"), True
