from tests.conftest import valid_payload


def test_create_rejects_urgency_category_out_of_range(client):
    response = client.post("/emergency-calls", json=valid_payload(urgency_category=5))
    assert response.status_code == 400
    assert response.json()["field"] == "urgency_category"


def test_create_rejects_arrival_before_receipt(client):
    payload = valid_payload()
    payload["received_at"], payload["arrived_at"] = payload["arrived_at"], payload["received_at"]
    response = client.post("/emergency-calls", json=payload)
    assert response.status_code == 400


def test_create_ignores_client_supplied_id(client):
    payload = valid_payload()
    payload["id"] = "11111111-1111-1111-1111-111111111111"
    response = client.post("/emergency-calls", json=payload)
    assert response.status_code == 201
    assert response.json()["id"] != payload["id"]


def test_get_malformed_id_returns_400_not_422(client):
    response = client.get("/emergency-calls/not-a-uuid")
    assert response.status_code == 400


def test_list_rejects_limit_above_max(client):
    response = client.get("/emergency-calls", params={"limit": 10_000})
    assert response.status_code == 400
    assert response.json()["field"] == "limit"
