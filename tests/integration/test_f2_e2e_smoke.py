"""F2 E2E smoke: 发布能力模型 → 上传简历（mock parse）→ 见到匹配结果"""
import pytest
import sqlalchemy as sa
from unittest.mock import patch, AsyncMock
from app.modules.matching.models import MatchingResult
from app.modules.resume.models import Resume
from app.modules.screening.models import Job


@pytest.mark.asyncio
async def test_e2e_smoke(db_session, db_engine, client, monkeypatch):
    # Redirect the audit logger's session factory to the test engine so that
    # audit_events written by log_event() are visible via db_session.
    from app.core.audit import logger as audit_logger
    monkeypatch.setattr(
        audit_logger, "_session_factory",
        sa.orm.sessionmaker(bind=db_engine),
    )

    # 1. 模拟已有岗位 + 已发布的能力模型
    cm = {
        "hard_skills": [
            {"name": "Python", "weight": 10, "must_have": True, "canonical_id": None, "level": "熟练"},
        ],
        "experience": {"years_min": 3, "years_max": 8, "industries": ["互联网"]},
        "education": {"min_level": "本科"},
        "job_level": "高级",
    }
    job = Job(title="后端工程师", is_active=True, required_skills="",
              competency_model=cm, competency_model_status="approved", user_id=1)
    db_session.add(job); db_session.commit()

    # 2. 模拟简历入库（已解析完成）
    resume = Resume(
        name="张三", phone="13900000001", email="t@x.com",
        skills="Python, Go, FastAPI",
        work_experience="在某互联网公司担任后端 5 年",
        work_years=5, education="本科", seniority="高级",
        ai_parsed="yes", source="manual", user_id=1,
    )
    db_session.add(resume); db_session.commit()

    # 3. 手动触发 T1 (模拟解析 worker 完成调用 triggers)
    from app.modules.matching.triggers import on_resume_parsed
    with patch("app.modules.matching.service.enhance_evidence_with_llm",
               new=AsyncMock(side_effect=lambda ev, *a, **kw: ev)), \
         patch("app.modules.matching.scorers.skill._max_vector_similarity", return_value=0.95):
        await on_resume_parsed(db_session, resume.id)

    # 4. 验证 matching_results 有行
    rows = db_session.query(MatchingResult).filter_by(
        resume_id=resume.id, job_id=job.id
    ).all()
    assert len(rows) == 1

    # 5. 经 API 读取
    resp = client.get(f"/api/matching/results?job_id={job.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    item = data["items"][0]
    assert item["resume_name"] == "张三"
    assert item["total_score"] > 50   # sanity check: 完全匹配的简历应 > 50
    assert item["hard_gate_passed"] is True
    assert item["stale"] is False

    # 6. 验证 audit_log
    from app.core.audit.models import AuditEvent
    db_session.expire_all()
    audits = db_session.query(AuditEvent).filter_by(entity_type="matching_result").all()
    assert len(audits) >= 1
