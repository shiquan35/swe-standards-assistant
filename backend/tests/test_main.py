def test_healthcheck_endpoint(client):
    resp = client.get("/healthcheck")
    assert resp.status_code == 200
    assert resp.json() == {"healthcheck": "OK!"}
