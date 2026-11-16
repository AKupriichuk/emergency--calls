from app.metrics import CgroupThrottleCollector, parse_cpu_stat


def test_metrics_endpoint_reports_request_count_and_duration(client):
    client.get("/emergency-calls", params={"limit": 1})
    response = client.get("/metrics")
    assert response.status_code == 200
    body = response.text
    assert 'http_requests_total{code="200",method="GET",path="/emergency-calls"}' in body
    assert "http_request_duration_seconds_bucket" in body
    assert "http_requests_in_progress" in body


def test_parse_cpu_stat_reads_periods_and_throttled():
    text = "nr_periods 120\nnr_throttled 4\nthrottled_usec 5000\n"
    assert parse_cpu_stat(text) == {"nr_periods": 120, "nr_throttled": 4, "throttled_usec": 5000}


def test_collector_yields_nothing_when_file_missing(monkeypatch):
    monkeypatch.setattr("app.metrics.find_cpu_stat_path", lambda: None)
    families = list(CgroupThrottleCollector().collect())
    assert families == []


def test_metrics_endpoint_survives_missing_cgroup_file(client, monkeypatch):
    monkeypatch.setattr("app.metrics.find_cpu_stat_path", lambda: None)
    response = client.get("/metrics")
    assert response.status_code == 200
