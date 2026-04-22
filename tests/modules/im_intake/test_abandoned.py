from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock
import pytest
from app.adapters.boss.base import BossCandidate
from app.modules.im_intake.service import IntakeService
from app.modules.im_intake.models import IntakeSlot
from app.modules.resume.models import Resume
from app.modules.screening.models import Job


@pytest.mark.asyncio
async def test_abandoned_when_pdf_72h_no_response(db_session, tmp_path):
    job = Job(title="前端", competency_model={"assessment_dimensions": []})
    db_session.add(job); db_session.commit()
    r = Resume(name="王五", boss_id="bx3", job_id=job.id, intake_status="awaiting_reply",
               intake_started_at=datetime.now(timezone.utc), source="boss_zhipin", status="passed")
    db_session.add(r); db_session.commit()
    db_session.add(IntakeSlot(resume_id=r.id, slot_key="pdf", slot_category="pdf",
                              ask_count=1, asked_at=datetime.now(timezone.utc) - timedelta(hours=73)))
    for k in ("arrival_date", "free_slots", "intern_duration"):
        db_session.add(IntakeSlot(resume_id=r.id, slot_key=k, slot_category="hard"))
    db_session.commit()

    adapter = AsyncMock()
    adapter.get_chat_messages = AsyncMock(return_value=[])
    adapter.list_received_resumes = AsyncMock(return_value=[])

    svc = IntakeService(db=db_session, adapter=adapter, llm=None,
                        storage_dir=str(tmp_path), pdf_timeout_hours=72)
    await svc.process_one(BossCandidate(name="王五", boss_id="bx3", job_intention="前端"))

    db_session.refresh(r)
    assert r.intake_status == "abandoned"
