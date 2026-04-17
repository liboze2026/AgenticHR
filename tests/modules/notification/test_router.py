"""通知 API 路由测试"""

def test_list_logs_empty(client):
    resp = client.get("/api/notification/logs")
    assert resp.status_code == 200
    assert resp.json()["total"] == 0
