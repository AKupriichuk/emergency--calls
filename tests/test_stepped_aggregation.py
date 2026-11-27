import pytest

from loadgen.stepped import RequestResult, SecondSummary, aggregate_phase, should_stop, window_average_achieved


def test_aggregate_phase_counts_only_2xx_as_achieved():
    rows = [
        RequestResult(scheduled_ts=0.2, done_ts=0.3, status_code=200, error=""),
        RequestResult(scheduled_ts=0.5, done_ts=0.6, status_code=502, error=""),
        RequestResult(scheduled_ts=0.7, done_ts=0.9, status_code=0, error="timeout"),
    ]
    summaries = aggregate_phase(rows, phase_start=0.0, duration_s=1, target_rate=3.0)
    assert summaries[0].achieved_rate == 1
    assert summaries[0].count_2xx == 1
    assert summaries[0].count_non_2xx == 2
    assert summaries[0].count_conn_errors == 0


def test_aggregate_phase_does_not_drop_completions_past_the_nominal_window():
    # scheduled inside the 1s window, but done_ts lands after duration_s=1 --
    # a late straggler must still be counted, not silently discarded.
    rows = [
        RequestResult(scheduled_ts=0.9, done_ts=0.95, status_code=200, error=""),
        RequestResult(scheduled_ts=0.9, done_ts=2.3, status_code=200, error=""),
    ]
    summaries = aggregate_phase(rows, phase_start=0.0, duration_s=1, target_rate=1.0)
    total_counted = sum(s.count_2xx + s.count_non_2xx for s in summaries)
    assert total_counted == 2
    assert len(summaries) > 1  # the straggler got its own second, past duration_s


def test_aggregate_phase_counts_a_result_past_timeout_as_non_2xx_even_if_status_is_200():
    # the HTTP call itself returned 200, but only after far longer than the
    # 5s timeout measured from the *scheduled* time -- spec: a request that
    # exceeds the timeout counts as non-2xx, and that must be judged from
    # the scheduled send time, not the actual dispatch time.
    rows = [RequestResult(scheduled_ts=0.0, done_ts=9.0, status_code=200, error="")]
    summaries = aggregate_phase(rows, phase_start=0.0, duration_s=10, target_rate=1.0, timeout_s=5.0)
    done_second = summaries[9]
    assert done_second.count_2xx == 0
    assert done_second.count_non_2xx == 1


def test_aggregate_phase_uses_scheduled_time_for_latency():
    rows = [RequestResult(scheduled_ts=10.0, done_ts=10.05, status_code=200, error="")]
    # dispatched late (actual send unknown/irrelevant here) but scheduled at t=10.0
    summaries = aggregate_phase(rows, phase_start=10.0, duration_s=1, target_rate=1.0)
    assert summaries[0].p50_ms == pytest.approx(50.0, abs=0.01)


def test_window_average_excludes_first_5s_of_a_20s_step():
    summaries = [
        SecondSummary(second=i, target_rate=200, actual_send_rate=200,
                       achieved_rate=(50 if i < 5 else 200), count_2xx=200,
                       count_non_2xx=0, count_conn_errors=0, p50_ms=1, p95_ms=1, p99_ms=1)
        for i in range(20)
    ]
    mean, _ = window_average_achieved(summaries, transient_s=5, window_s=15)
    assert mean == pytest.approx(200.0)


def test_should_stop_after_two_consecutive_shortfalls():
    stop, n = should_stop(step_avg_achieved=170, target_rate=200, g_limit=None, consecutive_below=0)
    assert (stop, n) == (False, 1)
    stop, n = should_stop(step_avg_achieved=170, target_rate=200, g_limit=None, consecutive_below=1)
    assert (stop, n) == (True, 2)


def test_should_stop_resets_counter_on_a_healthy_step():
    stop, n = should_stop(step_avg_achieved=200, target_rate=200, g_limit=None, consecutive_below=1)
    assert (stop, n) == (False, 0)


def test_should_stop_at_generator_ceiling():
    stop, n = should_stop(step_avg_achieved=5000, target_rate=5000, g_limit=4800, consecutive_below=0)
    assert stop is True
