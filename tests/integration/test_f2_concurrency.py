"""F2 并发打分测试."""
import asyncio
import pytest
import sqlalchemy as sa
from unittest.mock import patch, AsyncMock
from app.modules.matching.models import MatchingResult
from app.modules.matching.service import MatchingService
from app.core.audit.models import AuditEvent
from app.modules.resume.models import Resume
from app.modules.screening.models import Job


NO_LLM = patch(
    "app.modules.matching.service.enhance_evidence_with_llm",
    new=AsyncMock(side_effect=lambda ev, *a, **kw: ev),
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
async def test_two_parallel_score_pair_single_row(db_session, db_engine, monkeypatch):
    """两个并行 score_pair(r, j) → DB 中恰好 1 行, 审计记录 2 条."""
    from app.core.audit import logger as audit_logger
    monkeypatch.setattr(
        audit_logger, "_session_factory",
        sa.orm.sessionmaker(bind=db_engine),
    )

    job = _mk_job(db_session)
    resume = _mk_resume(db_session)
    service = MatchingService(db_session)

    before = db_session.query(AuditEvent).filter_by(entity_type="matching_result").count()

    with NO_LLM:
        await asyncio.gather(
            service.score_pair(resume.id, job.id, triggered_by="T1"),
            service.score_pair(resume.id, job.id, triggered_by="T1"),
        )

    row_count = db_session.query(MatchingResult).filter_by(
        resume_id=resume.id, job_id=job.id
    ).count()
    assert row_count == 1

    db_session.expire_all()
    after = db_session.query(AuditEvent).filter_by(entity_type="matching_result").count()
    assert after == before + 2


@pytest.mark.asyncio
async def test_sequential_10_score_pair_single_row_10_audits(db_session, db_engine, monkeypatch):
    """顺序 10 次 score_pair → 1 行, 10 条审计, scored_at 是最新时间."""
    from app.core.audit import logger as audit_logger
    monkeypatch.setattr(
        audit_logger, "_session_factory",
        sa.orm.sessionmaker(bind=db_engine),
    )

    job = _mk_job(db_session)
    resume = _mk_resume(db_session)
    service = MatchingService(db_session)

    before = db_session.query(AuditEvent).filter_by(entity_type="matching_result").count()
    last_result = None

    with NO_LLM:
        for _ in range(10):
            last_result = await service.score_pair(resume.id, job.id, triggered_by="T4")

    row_count = db_session.query(MatchingResult).filter_by(
        resume_id=resume.id, job_id=job.id
    ).count()
    assert row_count == 1

    db_session.expire_all()
    after = db_session.query(AuditEvent).filter_by(entity_type="matching_result").count()
    assert after == before + 10

    # scored_at 应是最后一次打分时间
    row = db_session.query(MatchingResult).filter_by(
        resume_id=resume.id, job_id=job.id
    ).one()
    assert last_result is not None
    assert row.scored_at == last_result.scored_at
