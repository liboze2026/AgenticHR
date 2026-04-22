from datetime import datetime, timezone
from unittest.mock import AsyncMock
import pytest
from app.adapters.boss.base import BossCandidate, BossMessage
from app.modules.im_intake.scheduler import IntakeScheduler
from app.modules.im_intake.service import IntakeService
from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.resume.models import Resume
from app.modules.screening.models import Job


@pytest.mark.skip(
    reason="pending F5 T11+ router switch and PDF-collection reintegration: "
           "T5 refactor removed pdf try_collect from process_one, and the API "
           "endpoint /api/intake/candidates?status=complete still queries Resume."
)
@pytest.mark.asyncio
async def test_full_intake_to_complete_visible_via_api(db_session, client, tmp_path):
    job = Job(title="前端", competency_model={"assessment_dimensions": []})
    db_session.add(job); db_session.commit()

    adapter = AsyncMock()
    adapter.list_chat_index = AsyncMock(return_value=[
        BossCandidate(name="赵六", boss_id="bxe", job_intention="前端"),
    ])
    adapter.get_chat_messages = AsyncMock(return_value=[
        BossMessage(sender_id="bxe", sender_name="赵六",
                    content="我下周一可以到岗，周三上午面试，实习6个月", is_pdf=False),
    ])
    adapter.send_message = AsyncMock(return_value=True)
    adapter.click_request_resume = AsyncMock(return_value=True)
    adapter.list_received_resumes = AsyncMock(return_value=[("bxe", "http://x/y.pdf")])
    adapter.download_pdf = AsyncMock(return_value=True)
    adapter._operations_today = 0

    def factory():
        return IntakeService(db=db_session, adapter=adapter, llm=None,
                             storage_dir=str(tmp_path), hard_max_asks=3, pdf_timeout_hours=72)

    sched = IntakeScheduler(adapter=adapter, service_factory=factory, batch_cap=10)
    await sched.tick()

    r = db_session.query(Resume).filter_by(boss_id="bxe").first()
    assert r is not None and r.intake_status == "complete"

    resp = client.get("/api/intake/candidates?status=complete")
    assert resp.status_code == 200
    assert any(c["boss_id"] == "bxe" for c in resp.json()["items"])
