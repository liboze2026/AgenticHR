"""AI 评估 API 路由测试"""


def test_ai_status(client):
    response = client.get("/api/ai/status")
    assert response.status_code == 200
    assert "enabled" in response.json()
