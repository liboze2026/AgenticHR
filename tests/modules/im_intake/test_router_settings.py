"""HTTP API for /api/intake/settings."""


def test_get_settings_creates_defaults(client):
    r = client.get("/api/intake/settings")
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is False
    assert body["target_count"] == 0
    assert body["complete_count"] == 0
    assert body["is_running"] is False


def test_put_settings_updates_fields(client):
    r = client.put("/api/intake/settings",
                   json={"enabled": True, "target_count": 50})
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is True
    assert body["target_count"] == 50


def test_put_settings_rejects_negative_target(client):
    r = client.put("/api/intake/settings",
                   json={"target_count": -1})
    assert r.status_code == 422


def test_put_settings_partial_keeps_other_field(client):
    client.put("/api/intake/settings", json={"target_count": 30, "enabled": True})
    r = client.put("/api/intake/settings", json={"enabled": False})
    body = r.json()
    assert body["enabled"] is False
    assert body["target_count"] == 30
