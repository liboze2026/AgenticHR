"""面试安排 API 路由测试"""
from datetime import datetime, timezone, timedelta


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _create_resume_via_api(client) -> int:
    resp = client.post("/api/resumes/", json={
        "name": "路由测试候选人",
        "phone": "13900000001",
    })
    return resp.json()["id"]


def test_create_interviewer_api(client):
    # 直接提供 feishu_user_id 绕过自动反查（反查需要真实飞书通讯录权限）
    response = client.post("/api/scheduling/interviewers", json={
        "name": "API面试官",
        "email": "api@test.com",
        "department": "工程部",
        "feishu_user_id": "ou_test_api_1",
    })
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "API面试官"
    assert data["id"] is not None


def test_create_interviewer_requires_contact_info(client):
    """没填 phone/email/feishu_user_id 任何一项 → 422"""
    response = client.post("/api/scheduling/interviewers", json={"name": "X"})
    assert response.status_code == 422


def test_list_interviewers_api(client):
    client.post("/api/scheduling/interviewers", json={"name": "面试官A", "feishu_user_id": "ou_a"})
    client.post("/api/scheduling/interviewers", json={"name": "面试官B", "feishu_user_id": "ou_b"})

    response = client.get("/api/scheduling/interviewers")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert len(data["items"]) == 2


def test_create_interview_api(client):
    resume_id = _create_resume_via_api(client)

    iv_resp = client.post("/api/scheduling/interviewers", json={
        "name": "面试官C", "feishu_user_id": "ou_c",
    })
    interviewer_id = iv_resp.json()["id"]

    tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
    start = tomorrow.replace(hour=10, minute=0, second=0, microsecond=0)
    end = tomorrow.replace(hour=11, minute=0, second=0, microsecond=0)

    response = client.post("/api/scheduling/interviews", json={
        "resume_id": resume_id,
        "interviewer_id": interviewer_id,
        "start_time": _iso(start),
        "end_time": _iso(end),
    })
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "scheduled"
    assert data["resume_id"] == resume_id


def test_cancel_interview_api(client):
    resume_id = _create_resume_via_api(client)

    iv_resp = client.post("/api/scheduling/interviewers", json={
        "name": "面试官D", "feishu_user_id": "ou_d",
    })
    interviewer_id = iv_resp.json()["id"]

    tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
    start = tomorrow.replace(hour=14, minute=0, second=0, microsecond=0)
    end = tomorrow.replace(hour=15, minute=0, second=0, microsecond=0)

    create_resp = client.post("/api/scheduling/interviews", json={
        "resume_id": resume_id,
        "interviewer_id": interviewer_id,
        "start_time": _iso(start),
        "end_time": _iso(end),
    })
    interview_id = create_resp.json()["id"]

    response = client.post(f"/api/scheduling/interviews/{interview_id}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
