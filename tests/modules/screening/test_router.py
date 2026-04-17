"""岗位管理与筛选 API 路由测试"""


def test_create_job_api(client):
    response = client.post("/api/screening/jobs", json={
        "title": "Python开发",
        "education_min": "本科",
        "work_years_min": 2,
        "required_skills": "Python,Django",
    })
    assert response.status_code == 201
    assert response.json()["title"] == "Python开发"


def test_list_jobs_api(client):
    client.post("/api/screening/jobs", json={"title": "岗位A"})
    client.post("/api/screening/jobs", json={"title": "岗位B"})
    response = client.get("/api/screening/jobs")
    assert response.status_code == 200
    assert response.json()["total"] == 2


def test_update_job_api(client):
    resp = client.post("/api/screening/jobs", json={"title": "旧"})
    job_id = resp.json()["id"]
    response = client.patch(f"/api/screening/jobs/{job_id}", json={"title": "新"})
    assert response.status_code == 200
    assert response.json()["title"] == "新"


def test_delete_job_api(client):
    resp = client.post("/api/screening/jobs", json={"title": "删除测试"})
    job_id = resp.json()["id"]
    response = client.delete(f"/api/screening/jobs/{job_id}")
    assert response.status_code == 204


def test_screen_resumes_api(client):
    job_resp = client.post("/api/screening/jobs", json={
        "title": "测试筛选",
        "education_min": "本科",
        "work_years_min": 2,
        "required_skills": "Python",
    })
    job_id = job_resp.json()["id"]

    client.post("/api/resumes/", json={
        "name": "合格候选人", "phone": "10000000101",
        "education": "本科", "work_years": 3, "skills": "Python,Django",
    })
    client.post("/api/resumes/", json={
        "name": "不合格候选人", "phone": "10000000102",
        "education": "大专", "work_years": 1, "skills": "HTML",
    })

    response = client.post(f"/api/screening/jobs/{job_id}/screen")
    assert response.status_code == 200
    data = response.json()
    assert data["passed"] == 1
    assert data["rejected"] == 1
