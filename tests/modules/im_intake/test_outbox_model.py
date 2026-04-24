from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base
import app.modules.auth.models  # noqa: F401 — register users table for FK
from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.im_intake.outbox_model import IntakeOutbox


def _make_session():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def test_outbox_model_roundtrip_and_defaults():
    db = _make_session()
    c = IntakeCandidate(user_id=1, boss_id="bx1", name="张三", intake_status="collecting",
                        source="plugin",
                        intake_started_at=datetime.now(timezone.utc))
    db.add(c); db.commit()
    ob = IntakeOutbox(candidate_id=c.id, user_id=1, action_type="send_hard",
                      text="请问您的薪资期望？", slot_keys=["salary_expectation"])
    db.add(ob); db.commit()
    db.refresh(ob)
    assert ob.id > 0
    assert ob.status == "pending"
    assert ob.attempts == 0
    assert ob.slot_keys == ["salary_expectation"]


def test_intake_candidate_has_expires_at():
    db = _make_session()
    now = datetime.now(timezone.utc)
    c = IntakeCandidate(user_id=1, boss_id="bx2", name="李四", intake_status="collecting",
                        source="plugin", intake_started_at=now, expires_at=now)
    db.add(c); db.commit(); db.refresh(c)
    # SQLite strips tzinfo on round-trip; compare naive components.
    assert c.expires_at is not None
    assert c.expires_at.replace(tzinfo=timezone.utc) == now
