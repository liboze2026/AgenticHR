"""ResumeResponse 需要暴露 intake_status 字段，前端 /resumes 才能按它过滤。"""
from app.modules.resume.models import Resume


def test_resume_detail_response_includes_intake_status(client, db_session):
    """通过 API 创建后直接在 DB 更新 intake_status，再 GET 确认字段被序列化。"""
    create = client.post(
        "/api/resumes/",
        json={"name": "Schema详情", "phone": "13811110002", "source": "manual"},
    )
    assert create.status_code == 201
    rid = create.json()["id"]

    # 直接在 DB 把 intake_status 改为 complete（模拟 promote 后状态）
    row = db_session.query(Resume).filter_by(id=rid).first()
    assert row is not None
    row.intake_status = "complete"
    db_session.commit()

    detail = client.get(f"/api/resumes/{rid}")
    assert detail.status_code == 200
    body = detail.json()
    assert "intake_status" in body, f"ResumeResponse 未暴露 intake_status: {body!r}"
    assert body["intake_status"] == "complete"


def test_resume_list_response_includes_intake_status(client, db_session):
    create = client.post(
        "/api/resumes/",
        json={"name": "Schema列表", "phone": "13811110003", "source": "boss_zhipin"},
    )
    assert create.status_code == 201
    rid = create.json()["id"]

    row = db_session.query(Resume).filter_by(id=rid).first()
    row.intake_status = "collecting"
    db_session.commit()

    resp = client.get("/api/resumes/")
    assert resp.status_code == 200
    items = resp.json()["items"]
    match = next((x for x in items if x["id"] == rid), None)
    assert match is not None
    assert match.get("intake_status") == "collecting"
