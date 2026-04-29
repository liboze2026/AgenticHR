"""ResumeResponse 需要暴露 intake_status 字段，前端 /resumes 才能按它过滤。

PR4 起 GET /api/resumes/ 数据源为 IntakeCandidate（四项齐全谓词）。
"""
from app.modules.resume.models import Resume
from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.im_intake.models import IntakeSlot
from app.modules.im_intake.templates import HARD_SLOT_KEYS


def _seed_complete_candidate(db_session, name="测试人", boss_id="b_seed",
                             intake_status="complete", user_id=1):
    c = IntakeCandidate(
        user_id=user_id, boss_id=boss_id, name=name,
        pdf_path="data/x.pdf", intake_status=intake_status,
    )
    db_session.add(c)
    db_session.commit()
    db_session.refresh(c)
    for k in HARD_SLOT_KEYS:
        db_session.add(IntakeSlot(
            candidate_id=c.id, slot_key=k, slot_category="hard",
            value="filled", ask_count=1,
        ))
    db_session.commit()
    return c


def test_resume_detail_response_includes_intake_status(client, db_session):
    """detail endpoint 仍返回旧 Resume 表 (单条 GET)，验证字段暴露未变。"""
    create = client.post(
        "/api/resumes/",
        json={"name": "Schema详情", "phone": "13811110002", "source": "manual"},
    )
    assert create.status_code == 201
    rid = create.json()["id"]

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
    """list endpoint 数据源为 IntakeCandidate; intake_status 字段必须暴露"""
    c = _seed_complete_candidate(db_session, name="Schema列表", boss_id="b_list",
                                 intake_status="complete", user_id=1)

    resp = client.get("/api/resumes/")
    assert resp.status_code == 200
    items = resp.json()["items"]
    match = next((x for x in items if x["id"] == c.id), None)
    assert match is not None, f"未找到 candidate id={c.id}"
    assert match.get("intake_status") == "complete"
