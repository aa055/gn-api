def test_health(client):
    assert client.get("/health").status_code == 200


def test_unknown_route_uses_error_shape(client):
    res = client.get("/nope")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "NOT_FOUND"
