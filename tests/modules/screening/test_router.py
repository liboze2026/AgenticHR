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

    r1 = client.post("/api/resumes/", json={
        "name": "合格候选人", "phone": "13900000101",
        "education": "本科", "work_years": 3, "skills": "Python,Django",
    })
    r2 = client.post("/api/resumes/", json={
        "name": "不合格候选人", "phone": "13900000102",
        "education": "大专", "work_years": 1, "skills": "HTML",
    })
    resume1_id = r1.json()["id"]
    resume2_id = r2.json()["id"]

    response = client.post(f"/api/screening/jobs/{job_id}/screen")
    assert response.status_code == 200
    data = response.json()
    assert data["passed"] == 1
    assert data["rejected"] == 1

    # 核心断言：screening 不得修改简历的全局 status（per-job 状态由 matching_results 管理）
    r1_after = client.get(f"/api/resumes/{resume1_id}").json()
    r2_after = client.get(f"/api/resumes/{resume2_id}").json()
    assert r1_after["status"] == "passed", f"合格候选人 status 被意外修改为 {r1_after['status']}"
    assert r2_after["status"] == "passed", f"不合格候选人 status 被意外修改为 {r2_after['status']}"


def test_job_batch_collect_criteria_create(client):
    resp = client.post("/api/screening/jobs", json={
        "title": "批采测试岗",
        "batch_collect_criteria": {"school_tiers": ["985", "211"], "education_min": "本科"},
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["batch_collect_criteria"]["school_tiers"] == ["985", "211"]
    assert data["batch_collect_criteria"]["education_min"] == "本科"


def test_job_batch_collect_criteria_update(client):
    resp = client.post("/api/screening/jobs", json={"title": "批采更新岗"})
    job_id = resp.json()["id"]
    resp2 = client.patch(f"/api/screening/jobs/{job_id}", json={
        "batch_collect_criteria": {"school_tiers": [], "education_min": None}
    })
    assert resp2.status_code == 200
    assert resp2.json()["batch_collect_criteria"]["school_tiers"] == []


def test_job_batch_collect_criteria_null_by_default(client):
    resp = client.post("/api/screening/jobs", json={"title": "默认岗"})
    assert resp.status_code == 201
    assert resp.json()["batch_collect_criteria"] is None
