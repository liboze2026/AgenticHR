from datetime import datetime, timezone
from unittest.mock import AsyncMock
import pytest
from app.adapters.boss.base import BossCandidate
from app.modules.im_intake.service import IntakeService
from app.modules.im_intake.models import IntakeSlot
from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.screening.models import Job


@pytest.mark.asyncio
async def test_pending_human_when_hard_exhausted_pdf_present(db_session, tmp_path):
    job = Job(title="前端", competency_model={"assessment_dimensions": []})
    db_session.add(job); db_session.commit()
    c = IntakeCandidate(name="李四", boss_id="bx2", job_id=job.id,
                        intake_status="awaiting_reply",
                        intake_started_at=datetime.now(timezone.utc),
                        source="plugin")
    db_session.add(c); db_session.commit()
    for k in ("arrival_date", "free_slots", "intern_duration"):
        db_session.add(IntakeSlot(candidate_id=c.id, slot_key=k, slot_category="hard",
                                  ask_count=3, asked_at=datetime.now(timezone.utc)))
    pdf_slot = IntakeSlot(candidate_id=c.id, slot_key="pdf", slot_category="pdf",
                          value="data/resumes/bx2.pdf", source="received",
                          ask_count=1, answered_at=datetime.now(timezone.utc))
    db_session.add(pdf_slot); db_session.commit()

    adapter = AsyncMock()
    adapter.get_chat_messages = AsyncMock(return_value=[])
    adapter.list_received_resumes = AsyncMock(return_value=[])

    svc = IntakeService(db=db_session, adapter=adapter, llm=None,
                        storage_dir=str(tmp_path), hard_max_asks=3)
    await svc.process_one(BossCandidate(name="李四", boss_id="bx2", job_intention="前端"))

    db_session.refresh(c)
    assert c.intake_status == "pending_human"
