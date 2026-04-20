"""Tests for deprecated AI evaluation endpoints (return 410 Gone)."""


def test_evaluate_returns_410(client):
    resp = client.post("/api/ai/evaluate",
                       json={"resume_id": 1, "job_id": 2})
    assert resp.status_code == 410
    body = resp.json()
    assert "migrate_to" in body.get("detail", {}) or "migrate_to" in body


def test_evaluate_batch_returns_410(client):
    resp = client.post("/api/ai/evaluate/batch", json={"job_id": 1})
    assert resp.status_code == 410


def test_status_still_ok(client):
    resp = client.get("/api/ai/status")
    assert resp.status_code == 200
