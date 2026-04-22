import pytest
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base
from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.im_intake.models import IntakeSlot


def _session():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def test_candidate_insert_and_slot_fk():
    s = _session()
    c = IntakeCandidate(boss_id="bx123", name="张三", intake_status="collecting",
                        source="plugin", intake_started_at=datetime.now(timezone.utc))
    s.add(c); s.commit()
    assert c.id is not None

    slot = IntakeSlot(candidate_id=c.id, slot_key="arrival_date", slot_category="hard")
    s.add(slot); s.commit()
    assert slot.candidate_id == c.id


def test_candidate_boss_id_unique():
    s = _session()
    s.add(IntakeCandidate(boss_id="bx1", name="A", intake_status="collecting", source="plugin"))
    s.commit()
    s.add(IntakeCandidate(boss_id="bx1", name="B", intake_status="collecting", source="plugin"))
    with pytest.raises(Exception):
        s.commit()
