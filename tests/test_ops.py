def test_livez_does_not_touch_database(client, monkeypatch):
    # get_db override in conftest raises if called; livez must not depend on it
    response = client.get("/livez")
    assert response.status_code == 200


def test_response_carries_x_pod_header(client):
    response = client.get("/livez")
    assert "X-Pod" in response.headers
    assert response.headers["X-Pod"]  # non-empty; falls back to hostname
