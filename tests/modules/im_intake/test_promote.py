from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base
from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.im_intake.models import IntakeSlot
from app.modules.resume.models import Resume
from app.modules.im_intake.promote import promote_to_resume


def _s():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def test_promote_creates_resume_and_links():
    s = _s()
    c = IntakeCandidate(
        user_id=1,
        boss_id="bx1", name="李四", job_id=None, intake_status="collecting",
        source="plugin", pdf_path="/tmp/bx1.pdf",
        intake_started_at=datetime.now(timezone.utc),
    )
    s.add(c); s.commit()

    resume = promote_to_resume(s, c, user_id=1)
    s.commit()

    assert resume.id is not None
    assert resume.boss_id == "bx1"
    assert resume.name == "李四"
    assert resume.pdf_path == "/tmp/bx1.pdf"
    assert resume.intake_status == "complete"
    assert resume.status == "passed"

    s.refresh(c)
    assert c.promoted_resume_id == resume.id
    assert c.intake_status == "complete"
    assert c.intake_completed_at is not None


def test_promote_idempotent():
    s = _s()
    c = IntakeCandidate(user_id=1, boss_id="bx1", name="A",
                        intake_status="collecting", source="plugin")
    s.add(c); s.commit()
    r1 = promote_to_resume(s, c, user_id=1); s.commit()
    r2 = promote_to_resume(s, c, user_id=1); s.commit()
    assert r1.id == r2.id
    assert s.query(Resume).count() == 1


def test_promote_rejects_orphan_user_id():
    """BUG-047: user_id<=0 raises ValueError instead of creating orphan row."""
    import pytest
    s = _s()
    c = IntakeCandidate(user_id=1, boss_id="orph", name="O",
                        intake_status="collecting", source="plugin")
    s.add(c); s.commit()
    with pytest.raises(ValueError):
        promote_to_resume(s, c, user_id=0)
    with pytest.raises(ValueError):
        promote_to_resume(s, c, user_id=-1)
