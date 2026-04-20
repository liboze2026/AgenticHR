import pytest
import sqlalchemy as sa
from unittest.mock import patch, AsyncMock
from app.core.audit.models import AuditEvent
from app.modules.matching.service import MatchingService
from app.modules.resume.models import Resume
from app.modules.screening.models import Job


@pytest.mark.asyncio
async def test_score_writes_audit(db_session, db_engine, monkeypatch):
    # Redirect the audit logger's session factory to the test engine so that
    # audit_events written by log_event() are visible via db_session.
    from app.core.audit import logger as audit_logger
    monkeypatch.setattr(
        audit_logger, "_session_factory",
        sa.orm.sessionmaker(bind=db_engine),
    )

    j = Job(title="J", is_active=True, required_skills="",
            competency_model={"hard_skills": [], "experience": {}, "education": {}, "job_level": ""},
            competency_model_status="approved")
    db_session.add(j); db_session.commit()
    r = Resume(name="R", phone="", skills="Python", work_years=3,
               education="本科", ai_parsed="yes", source="manual", seniority="中级")
    db_session.add(r); db_session.commit()

    before = db_session.query(AuditEvent).filter_by(
        entity_type="matching_result"
    ).count()

    with patch("app.modules.matching.service.enhance_evidence_with_llm",
               new=AsyncMock(side_effect=lambda ev, *a, **kw: ev)):
        await MatchingService(db_session).score_pair(r.id, j.id)

    db_session.expire_all()
    after = db_session.query(AuditEvent).filter_by(
        entity_type="matching_result"
    ).count()
    assert after == before + 1
