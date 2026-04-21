"""F2 审计链条测试 — 多触发器产生多条审计记录."""
import pytest
import sqlalchemy as sa
from unittest.mock import patch, AsyncMock
from app.core.audit.models import AuditEvent
from app.modules.matching.service import MatchingService
from app.modules.matching.triggers import on_resume_parsed, on_competency_approved
from app.modules.resume.models import Resume
from app.modules.screening.models import Job


NO_LLM = patch(
    "app.modules.matching.service.enhance_evidence_with_llm",
    new=AsyncMock(side_effect=lambda ev, *a, **kw: ev),
)


def _setup_audit(monkeypatch, db_engine):
    """把 audit_logger 的 session_factory 重定向到测试引擎."""
    from app.core.audit import logger as audit_logger
    monkeypatch.setattr(
        audit_logger, "_session_factory",
        sa.orm.sessionmaker(bind=db_engine),
    )


def _mk_resume(session, **kw):
    defaults = dict(
        name="候选人", phone="", skills="Python",
        work_years=5, education="本科", seniority="高级",
        ai_parsed="yes", source="manual",
    )
    defaults.update(kw)
    r = Resume(**defaults)
    session.add(r)
    session.commit()
    return r


def _mk_job(session, **kw):
    defaults = dict(
        title="岗位", is_active=True, required_skills="",
        competency_model={
            "hard_skills": [],
            "experience": {"years_min": 0},
            "education": {},
            "job_level": "高级",
        },
        competency_model_status="approved",
    )
    defaults.update(kw)
    j = Job(**defaults)
    session.add(j)
    session.commit()
    return j


@pytest.mark.asyncio
async def test_t1_t3_t4_each_write_audit(db_session, db_engine, monkeypatch):
    """同一 (resume, job) 对通过 T1, T3, T4 各打分一次 → 3 条审计记录."""
    _setup_audit(monkeypatch, db_engine)

    job = _mk_job(db_session)
    resume = _mk_resume(db_session)
    service = MatchingService(db_session)

    before = db_session.query(AuditEvent).filter_by(entity_type="matching_result").count()

    with NO_LLM:
        await service.score_pair(resume.id, job.id, triggered_by="T1")
        await service.score_pair(resume.id, job.id, triggered_by="T3")
        await service.score_pair(resume.id, job.id, triggered_by="T4")

    db_session.expire_all()
    after = db_session.query(AuditEvent).filter_by(entity_type="matching_result").count()
    assert after == before + 3


@pytest.mark.asyncio
async def test_audit_events_have_correct_fields(db_session, db_engine, monkeypatch):
    """每条审计记录的 f_stage, action, entity_type 字段正确."""
    _setup_audit(monkeypatch, db_engine)

    job = _mk_job(db_session)
    resume = _mk_resume(db_session)

    with NO_LLM:
        result = await MatchingService(db_session).score_pair(resume.id, job.id, triggered_by="T4")

    db_session.expire_all()
    events = db_session.query(AuditEvent).filter_by(entity_type="matching_result").all()
    assert len(events) >= 1

    ev = events[-1]
    assert ev.f_stage == "F2"
    assert ev.action == "score"
    assert ev.entity_type == "matching_result"
    assert ev.entity_id == result.id


@pytest.mark.asyncio
async def test_audit_trigger_payload_written_to_disk(db_session, db_engine, monkeypatch, tmp_path):
    """审计 payload (含 trigger 字段) 写入磁盘文件, 并能读回."""
    _setup_audit(monkeypatch, db_engine)

    import os
    import json
    monkeypatch.setenv("AGENTICHR_AUDIT_DIR", str(tmp_path))
    # 重新导入 AUDIT_DIR 常量受限于模块已加载, 直接 patch 模块级变量
    import app.core.audit.logger as audit_module
    monkeypatch.setattr(audit_module, "AUDIT_DIR", str(tmp_path))

    job = _mk_job(db_session)
    resume = _mk_resume(db_session)

    with NO_LLM:
        await MatchingService(db_session).score_pair(resume.id, job.id, triggered_by="T4")

    db_session.expire_all()
    # DB 行必须存在
    events = db_session.query(AuditEvent).filter_by(entity_type="matching_result").all()
    assert len(events) >= 1

    # 磁盘文件必须存在并含 trigger 字段
    files = list(tmp_path.iterdir())
    assert len(files) >= 1

    payload = json.loads(files[-1].read_text(encoding="utf-8"))
    assert payload["input"].get("trigger") == "T4"


@pytest.mark.asyncio
async def test_audit_entity_id_points_to_matching_result(db_session, db_engine, monkeypatch):
    """audit entity_id 指向 matching_result 主键."""
    _setup_audit(monkeypatch, db_engine)

    job = _mk_job(db_session)
    resume = _mk_resume(db_session)

    with NO_LLM:
        result = await MatchingService(db_session).score_pair(resume.id, job.id)

    db_session.expire_all()
    from app.modules.matching.models import MatchingResult
    row = db_session.query(MatchingResult).filter_by(resume_id=resume.id, job_id=job.id).one()

    events = db_session.query(AuditEvent).filter_by(
        entity_type="matching_result", entity_id=row.id
    ).all()
    assert len(events) >= 1
