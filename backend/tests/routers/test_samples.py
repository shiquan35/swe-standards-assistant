from __future__ import annotations


def _create_sample(client) -> dict:
    payload = {
        "name": "Widget",
        "description": "Test widget",
        "price": 12.34,
        "is_active": True,
    }
    resp = client.post("/api/samples/", json=payload)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    for key in ("id", "created_at", "updated_at"):
        assert key in data
    return data


def test_create_and_get_sample(client):
    created = _create_sample(client)
    sample_id = created["id"]
    resp = client.get(f"/api/samples/{sample_id}")
    assert resp.status_code == 200
    fetched = resp.json()
    assert fetched["id"] == sample_id
    assert fetched["name"] == "Widget"


def test_list_samples_pagination(client):
    # Create two samples
    _create_sample(client)
    _create_sample(client)
    resp = client.get("/api/samples/")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert data["page"] == 1
    # Default page size from fastapi-pagination is 50 unless configured; just ensure >= 2 total
    assert data["total"] >= 2
    assert len(data["items"]) >= 2


def test_update_sample(client):
    created = _create_sample(client)
    sample_id = created["id"]
    original_updated_at = created["updated_at"]
    patch_payload = {"description": "Updated desc", "price": 99.99}
    resp = client.patch(f"/api/samples/{sample_id}", json=patch_payload)
    assert resp.status_code == 200, resp.text
    updated = resp.json()
    assert updated["description"] == "Updated desc"
    assert updated["price"] == 99.99
    # Ensure updated_at changed
    assert updated["updated_at"] != original_updated_at


def test_delete_sample_and_404_after(client):
    created = _create_sample(client)
    sample_id = created["id"]
    resp = client.delete(f"/api/samples/{sample_id}")
    assert resp.status_code == 200
    assert resp.json()["detail"] == f"ID: {sample_id} deleted"
    # Now should 404
    resp2 = client.get(f"/api/samples/{sample_id}")
    assert resp2.status_code == 404
