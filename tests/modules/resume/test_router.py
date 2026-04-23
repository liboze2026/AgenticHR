"""简历 API 路由测试"""


def test_create_resume_api(client):
    response = client.post(
        "/api/resumes/",
        json={
            "name": "测试候选人",
            "phone": "13800000001",
            "email": "test@example.com",
            "education": "本科",
            "work_years": 3,
            "source": "boss_zhipin",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "测试候选人"
    assert data["id"] is not None


def test_create_duplicate_resume_api(client):
    """重复提交应返回201并更新已有记录（不再报409）"""
    payload = {"name": "重复人", "phone": "13800000002", "source": "boss_zhipin"}
    resp1 = client.post("/api/resumes/", json=payload)
    assert resp1.status_code == 201
    resp2 = client.post("/api/resumes/", json=payload)
    assert resp2.status_code == 201
    assert resp2.json()["id"] == resp1.json()["id"]  # 返回同一条记录


def test_get_resume_api(client):
    create_resp = client.post(
        "/api/resumes/", json={"name": "查询测试", "phone": "13800000003"}
    )
    resume_id = create_resp.json()["id"]

    response = client.get(f"/api/resumes/{resume_id}")
    assert response.status_code == 200
    assert response.json()["name"] == "查询测试"


def test_get_resume_not_found(client):
    response = client.get("/api/resumes/99999")
    assert response.status_code == 404


def test_list_resumes_api(client):
    for i in range(3):
        client.post(
            "/api/resumes/", json={"name": f"列表测试{i}", "phone": f"1390000{i:04d}"}
        )

    response = client.get("/api/resumes/")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3
    assert len(data["items"]) == 3


def test_list_resumes_with_filters(client):
    client.post(
        "/api/resumes/",
        json={"name": "Java开发", "phone": "13800000010", "skills": "Java,Spring"},
    )
    client.post(
        "/api/resumes/",
        json={"name": "Python开发", "phone": "13800000011", "skills": "Python"},
    )

    response = client.get("/api/resumes/?keyword=Java")
    data = response.json()
    assert data["total"] == 1


def test_update_resume_api(client):
    create_resp = client.post(
        "/api/resumes/", json={"name": "更新测试", "phone": "13800000020"}
    )
    resume_id = create_resp.json()["id"]

    response = client.patch(
        f"/api/resumes/{resume_id}",
        json={"status": "passed"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "passed"


def test_delete_resume_api(client):
    create_resp = client.post(
        "/api/resumes/", json={"name": "删除测试", "phone": "13800000030"}
    )
    resume_id = create_resp.json()["id"]

    response = client.delete(f"/api/resumes/{resume_id}")
    assert response.status_code == 204

    response = client.get(f"/api/resumes/{resume_id}")
    assert response.status_code == 404


def test_batch_create_resumes_api(client):
    resumes = [
        {"name": f"批量{i}", "phone": f"1370000{i:04d}", "source": "boss_zhipin"}
        for i in range(5)
    ]
    response = client.post("/api/resumes/batch", json=resumes)
    assert response.status_code == 201
    data = response.json()
    assert data["created"] == 5
    assert data["duplicates"] == 0


def test_upload_pdf_resume(client, tmp_path):
    """上传 PDF 简历文件"""
    import os
    from reportlab.pdfgen import canvas
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    font_name = "Helvetica"
    for name, fpath in [
        ("SimSun", "C:/Windows/Fonts/simsun.ttc"),
        ("MicrosoftYaHei", "C:/Windows/Fonts/msyh.ttc"),
    ]:
        if os.path.exists(fpath):
            try:
                pdfmetrics.registerFont(TTFont(name, fpath))
                font_name = name
                break
            except Exception:
                pass

    pdf_path = str(tmp_path / "resume.pdf")
    c = canvas.Canvas(pdf_path)
    c.setFont(font_name, 12)
    c.drawString(72, 800, "王五")
    c.drawString(72, 785, "13800001111")
    c.drawString(72, 770, "wangwu@test.com")
    c.drawString(72, 755, "本科")
    c.save()

    with open(pdf_path, "rb") as f:
        response = client.post(
            "/api/resumes/upload",
            files={"file": ("resume.pdf", f, "application/pdf")},
        )
    assert response.status_code == 201
    data = response.json()
    assert data["pdf_path"] != ""


def test_upload_pdf_resume_with_boss_id(client, tmp_path):
    """上传 PDF 时若带 candidate_boss_id 表单字段，应回填 Resume.boss_id，
    使 F5 intake promote_to_resume 的 merge-by-boss_id 能找到该行。"""
    from reportlab.pdfgen import canvas
    pdf_path = str(tmp_path / "r.pdf")
    c = canvas.Canvas(pdf_path)
    c.setFont("Helvetica", 12)
    c.drawString(72, 800, "Test Name")
    c.save()
    with open(pdf_path, "rb") as f:
        response = client.post(
            "/api/resumes/upload",
            files={"file": ("r.pdf", f, "application/pdf")},
            data={"candidate_name": "测试候选", "candidate_boss_id": "77777-0"},
        )
    assert response.status_code == 201
    data = response.json()
    assert data.get("boss_id") == "77777-0"
