import json
from datetime import datetime, timedelta, timezone

import pytest
from unittest.mock import MagicMock, AsyncMock
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
async def test_analyze_chat_fills_slots_via_llm_and_returns_next_action():
    """Slot value must equal the candidate's verbatim phrase the LLM returned,
    not a regex-normalized token. No regex path exists anymore."""
    s = _s()
    c = IntakeCandidate(boss_id="bx1", name="王五", intake_status="collecting", source="plugin")
    s.add(c); s.commit()
    for k in HARD_SLOT_KEYS:
        s.add(IntakeSlot(candidate_id=c.id, slot_key=k, slot_category="hard"))
    s.add(IntakeSlot(candidate_id=c.id, slot_key="pdf", slot_category="pdf"))
    s.commit()

    llm = AsyncMock()
    llm.complete.return_value = json.dumps({
        "arrival_date": "明天能到",
        "intern_duration": "能实习6个月",
        "free_slots": None,
    })

    svc = IntakeService(db=s, adapter=MagicMock(), llm=llm, storage_dir="/tmp")
    messages = [{"sender_id": "bx1", "content": "明天能到，能实习6个月"}]
    action = await svc.analyze_chat(c, messages, job=None)
    s.refresh(c)

    by = {sl.slot_key: sl for sl in s.query(IntakeSlot).filter_by(candidate_id=c.id).all()}
    assert by["arrival_date"].value == "明天能到"
    assert by["arrival_date"].source == "llm"
    assert by["intern_duration"].value == "能实习6个月"
    assert by["free_slots"].value is None
    assert action.type == "send_hard"  # free_slots still missing, ask_count=0


@pytest.mark.asyncio
async def test_analyze_chat_without_llm_skips_extraction():
    """When llm=None, SlotFiller.parse_conversation returns {} — slots stay empty."""
    s = _s()
    c = IntakeCandidate(boss_id="bx1", name="王五", intake_status="collecting", source="plugin")
    s.add(c); s.commit()

    svc = IntakeService(db=s, adapter=MagicMock(), llm=None, storage_dir="/tmp")
    messages = [{"sender_id": "bx1", "content": "明天能到"}]
    action = await svc.analyze_chat(c, messages, job=None)

    by = {sl.slot_key: sl for sl in s.query(IntakeSlot).filter_by(candidate_id=c.id).all()}
    assert by["arrival_date"].value is None
    assert action.type == "send_hard"


def test_ensure_candidate_sets_expires_at_14_days_default(db_session):
    """New candidates must get expires_at set; otherwise cleanup_expired (which
    filters on expires_at IS NOT NULL) never prunes them, defeating the 14-day
    auto-abandon promise."""
    svc = IntakeService(db=db_session, user_id=1)
    c = svc.ensure_candidate(boss_id="bxNew", name="N")
    assert c.expires_at is not None
    expires = c.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    delta = expires - datetime.now(timezone.utc)
    # Default 14 days ± small clock jitter
    assert timedelta(days=13, hours=23) < delta < timedelta(days=14, hours=1)


def test_ensure_candidate_honors_f4_expires_days(db_session, monkeypatch):
    """f4_expires_days setting should drive the expiry window."""
    from app.modules.im_intake import service as _svc
    monkeypatch.setattr(_svc.settings, "f4_expires_days", 7, raising=False)
    svc = IntakeService(db=db_session, user_id=1)
    c = svc.ensure_candidate(boss_id="bx7d", name="W")
    expires = c.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    delta = expires - datetime.now(timezone.utc)
    assert timedelta(days=6, hours=23) < delta < timedelta(days=7, hours=1)
