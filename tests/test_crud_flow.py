from tests.conftest import valid_payload


def test_full_crud_cycle(client):
    created = client.post("/emergency-calls", json=valid_payload()).json()
    call_id = created["id"]

    assert client.get(f"/emergency-calls/{call_id}").status_code == 200

    listed = client.get("/emergency-calls").json()
    assert listed["total"] == 1
    assert listed["items"][0]["id"] == call_id
    assert listed["limit"] == 50
    assert listed["offset"] == 0

    updated = client.put(
        f"/emergency-calls/{call_id}", json=valid_payload(outcome="deceased")
    )
    assert updated.status_code == 200
    assert updated.json()["outcome"] == "deceased"

    first_delete = client.delete(f"/emergency-calls/{call_id}")
    assert first_delete.status_code == 204

    second_delete = client.delete(f"/emergency-calls/{call_id}")
    assert second_delete.status_code == 404


def test_list_filters_by_urgency_category(client):
    client.post("/emergency-calls", json=valid_payload(urgency_category=1))
    client.post("/emergency-calls", json=valid_payload(urgency_category=3))

    response = client.get("/emergency-calls", params={"urgency_category": 3})
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["urgency_category"] == 3


def test_healthz_returns_ok(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_get_missing_returns_404(client):
    response = client.get("/emergency-calls/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


def test_put_missing_returns_404(client):
    response = client.put(
        "/emergency-calls/00000000-0000-0000-0000-000000000000", json=valid_payload()
    )
    assert response.status_code == 404
