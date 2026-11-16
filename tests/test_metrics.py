def test_metrics_endpoint_reports_request_count_and_duration(client):
    client.get("/emergency-calls", params={"limit": 1})
    response = client.get("/metrics")
    assert response.status_code == 200
    body = response.text
    assert 'http_requests_total{code="200",method="GET",path="/emergency-calls"}' in body
    assert "http_request_duration_seconds_bucket" in body
    assert "http_requests_in_progress" in body
