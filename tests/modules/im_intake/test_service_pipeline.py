from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
import pytest
from app.adapters.boss.base import BossCandidate, BossMessage
from app.modules.im_intake.service import IntakeService
from app.modules.im_intake.models import IntakeSlot
from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.resume.models import Resume
from app.modules.screening.models import Job


@pytest.mark.asyncio
async def test_first_round_creates_resume_and_sends_hard_questions(db_session, tmp_path):
    job = Job(title="前端开发工程师", competency_model={"assessment_dimensions": []})
    db_session.add(job); db_session.commit()

    adapter = AsyncMock()
    adapter.get_chat_messages = AsyncMock(return_value=[])
    adapter.send_message = AsyncMock(return_value=True)
    adapter.click_request_resume = AsyncMock(return_value=True)
    adapter.list_received_resumes = AsyncMock(return_value=[])

    svc = IntakeService(db=db_session, adapter=adapter, llm=None,
                        storage_dir=str(tmp_path), hard_max_asks=3, pdf_timeout_hours=72)
    cand = BossCandidate(name="张三", boss_id="bx1", job_intention="前端开发工程师")

    await svc.process_one(cand)

    c = db_session.query(IntakeCandidate).filter_by(boss_id="bx1").first()
    assert c is not None
    assert c.intake_status in ("collecting", "awaiting_reply")
    assert c.job_id == job.id
    slots = db_session.query(IntakeSlot).filter_by(candidate_id=c.id).all()
    assert {s.slot_key for s in slots} >= {"arrival_date", "free_slots", "intern_duration", "pdf"}
    adapter.send_message.assert_called_once()
    sent_text = adapter.send_message.call_args[0][1]
    assert "张三" in sent_text and ("到岗" in sent_text or "入职" in sent_text)


@pytest.mark.asyncio
async def test_second_round_parses_reply_and_fills_slots(db_session, tmp_path):
    job = Job(title="前端开发", competency_model={"assessment_dimensions": []})
    db_session.add(job); db_session.commit()
    c = IntakeCandidate(name="张三", boss_id="bx1", job_id=job.id,
                        intake_status="awaiting_reply",
                        intake_started_at=datetime.now(timezone.utc),
                        source="plugin")
    db_session.add(c); db_session.commit()
    for k in ("arrival_date", "free_slots", "intern_duration"):
        db_session.add(IntakeSlot(candidate_id=c.id, slot_key=k, slot_category="hard",
                                  ask_count=1, asked_at=datetime.now(timezone.utc)))
    db_session.add(IntakeSlot(candidate_id=c.id, slot_key="pdf", slot_category="pdf",
                              ask_count=1, asked_at=datetime.now(timezone.utc)))
    db_session.commit()

    adapter = AsyncMock()
    adapter.get_chat_messages = AsyncMock(return_value=[
        BossMessage(sender_id="bx1", sender_name="张三",
                    content="下周一可以到岗，周三下午有空，实习6个月", is_pdf=False),
    ])
    adapter.send_message = AsyncMock(return_value=True)
    adapter.list_received_resumes = AsyncMock(return_value=[])

    svc = IntakeService(db=db_session, adapter=adapter, llm=None,
                        storage_dir=str(tmp_path), hard_max_asks=3, pdf_timeout_hours=72)
    bc = BossCandidate(name="张三", boss_id="bx1", job_intention="前端开发")

    await svc.process_one(bc)

    db_session.refresh(c)
    arrival = db_session.query(IntakeSlot).filter_by(candidate_id=c.id, slot_key="arrival_date").first()
    intern = db_session.query(IntakeSlot).filter_by(candidate_id=c.id, slot_key="intern_duration").first()
    assert arrival.value == "下周一" and arrival.source == "regex"
    assert intern.value == "6个月"
