import pytest

from analysis.quantile import estimate_quantile


def test_estimate_quantile_interpolates_within_a_bucket():
    # buckets in seconds, matching Г3 (ms->s): 0.001..1.024, +inf
    buckets = [(0.001, 0), (0.002, 0), (0.004, 2), (0.008, 10), (float("inf"), 10)]
    estimate, error_bound, exceeds = estimate_quantile(buckets, q=0.5)
    # n=10, r=5 -> falls in (0.004, 0.008] bucket: c(i-1)=2, c(i)=10
    assert estimate == pytest.approx(0.004 + (0.008 - 0.004) * (5 - 2) / (10 - 2))
    assert error_bound == pytest.approx(0.004)
    assert exceeds is False


def test_estimate_quantile_reports_overflow_past_last_finite_bucket():
    buckets = [(0.001, 0), (0.002, 1), (float("inf"), 10)]
    estimate, error_bound, exceeds = estimate_quantile(buckets, q=0.99)
    assert estimate is None
    assert error_bound == float("inf")
    assert exceeds is True


def test_estimate_quantile_handles_first_bucket():
    buckets = [(0.001, 3), (float("inf"), 3)]
    estimate, error_bound, exceeds = estimate_quantile(buckets, q=0.5)
    assert estimate == pytest.approx(0.001 * (1.5 - 0) / (3 - 0))
    assert error_bound == pytest.approx(0.001)
