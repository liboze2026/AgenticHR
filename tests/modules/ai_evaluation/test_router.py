"""AI 评估 API 路由测试"""


def test_ai_status(client):
    response = client.get("/api/ai/status")
    assert response.status_code == 200
    assert "enabled" in response.json()


def test_evaluate_when_disabled(client, monkeypatch):
    from app.modules.ai_evaluation import router as ai_router
    monkeypatch.setattr(ai_router.settings, "ai_enabled", False)
    response = client.post("/api/ai/evaluate", json={"resume_id": 1, "job_id": 1})
    assert response.status_code == 400
    assert "未开启" in response.json()["detail"]


def test_batch_evaluate_when_disabled(client, monkeypatch):
    from app.modules.ai_evaluation import router as ai_router
    monkeypatch.setattr(ai_router.settings, "ai_enabled", False)
    response = client.post("/api/ai/evaluate/batch", json={"job_id": 1})
    assert response.status_code == 400
