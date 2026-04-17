"""飞书机器人路由测试"""
import json


def test_feishu_challenge(client):
    """飞书 URL 验证"""
    resp = client.post("/api/feishu/event", json={
        "challenge": "test_challenge_123",
        "token": "test_token",
        "type": "url_verification",
    })
    assert resp.status_code == 200
    assert resp.json()["challenge"] == "test_challenge_123"


def test_feishu_bot_status(client):
    resp = client.get("/api/feishu/status")
    assert resp.status_code == 200
    assert "configured" in resp.json()
