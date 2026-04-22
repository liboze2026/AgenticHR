from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock
import pytest
from app.modules.im_intake.pdf_collector import PdfCollector
from app.modules.im_intake.models import IntakeSlot


@pytest.mark.asyncio
async def test_collect_when_pdf_in_received_tab(tmp_path):
    adapter = AsyncMock()
    adapter.list_received_resumes = AsyncMock(return_value=[("bx", "http://x/y.pdf")])
    adapter.download_pdf = AsyncMock(return_value=True)
    slot = IntakeSlot(slot_key="pdf", slot_category="pdf", ask_count=1, asked_at=datetime.now(timezone.utc))

    pc = PdfCollector(adapter=adapter, storage_dir=str(tmp_path))
    pdf_path, status = await pc.try_collect(boss_id="bx", slot=slot)

    assert status == "received"
    assert pdf_path.endswith("bx.pdf")
    adapter.download_pdf.assert_called_once()


@pytest.mark.asyncio
async def test_request_when_first_attempt(tmp_path):
    adapter = AsyncMock()
    adapter.list_received_resumes = AsyncMock(return_value=[])
    adapter.click_request_resume = AsyncMock(return_value=True)
    slot = IntakeSlot(slot_key="pdf", slot_category="pdf", ask_count=0)

    pc = PdfCollector(adapter=adapter, storage_dir=str(tmp_path))
    pdf_path, status = await pc.try_collect(boss_id="bx", slot=slot)

    assert status == "requested"
    assert pdf_path is None
    adapter.click_request_resume.assert_called_once()


@pytest.mark.asyncio
async def test_abandon_after_72h(tmp_path):
    adapter = AsyncMock()
    adapter.list_received_resumes = AsyncMock(return_value=[])
    slot = IntakeSlot(
        slot_key="pdf", slot_category="pdf", ask_count=1,
        asked_at=datetime.now(timezone.utc) - timedelta(hours=73),
    )
    pc = PdfCollector(adapter=adapter, storage_dir=str(tmp_path), timeout_hours=72)
    pdf_path, status = await pc.try_collect(boss_id="bx", slot=slot)

    assert status == "abandon"
    assert pdf_path is None
    adapter.click_request_resume.assert_not_called()
