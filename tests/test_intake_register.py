from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_register_candidate_endpoint_exists():
    resp = client.post("/api/intake/candidates/register",
                       json={"boss_id": "test123", "name": "测试", "job_title": "工程师"})
    assert resp.status_code != 404, f"endpoint not found, got {resp.status_code}"

def test_mark_timed_out_endpoint_exists():
    resp = client.post("/api/intake/candidates/999/mark-timed-out")
    assert resp.status_code != 404, f"endpoint not found, got {resp.status_code}"

def test_last_checked_endpoint_exists():
    resp = client.patch("/api/intake/candidates/999/last-checked")
    assert resp.status_code != 404, f"endpoint not found, got {resp.status_code}"
