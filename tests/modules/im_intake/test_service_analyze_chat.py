import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base
from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.im_intake.models import IntakeSlot
from app.modules.im_intake.templates import HARD_SLOT_KEYS
from app.modules.im_intake.service import IntakeService


def _s():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


@pytest.mark.asyncio
async def test_analyze_chat_fills_slots_and_returns_next_action():
    s = _s()
    c = IntakeCandidate(boss_id="bx1", name="王五", intake_status="collecting", source="plugin")
    s.add(c); s.commit()
    for k in HARD_SLOT_KEYS:
        s.add(IntakeSlot(candidate_id=c.id, slot_key=k, slot_category="hard"))
    s.add(IntakeSlot(candidate_id=c.id, slot_key="pdf", slot_category="pdf"))
    s.commit()

    svc = IntakeService(db=s, adapter=MagicMock(), llm=None, storage_dir="/tmp")
    messages = [{"sender_id": "bx1", "content": "明天能到，能实习6个月"}]
    action = await svc.analyze_chat(c, messages, job=None)
    s.refresh(c)

    by = {sl.slot_key: sl for sl in s.query(IntakeSlot).filter_by(candidate_id=c.id).all()}
    assert by["arrival_date"].value == "明天"
    assert by["intern_duration"].value == "6个月"
    assert action.type == "send_hard"  # free_slots still missing, ask_count=0 so still pending
