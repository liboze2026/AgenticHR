import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Literal, Protocol
from app.modules.im_intake.models import IntakeSlot

logger = logging.getLogger(__name__)

CollectStatus = Literal["received", "requested", "waiting", "abandon", "error"]


class AdapterLike(Protocol):
    async def list_received_resumes(self) -> list[tuple[str, str]]: ...
    async def download_pdf(self, pdf_url: str, save_path: str) -> bool: ...
    async def click_request_resume(self, boss_id: str) -> bool: ...


class PdfCollector:
    def __init__(self, adapter: AdapterLike, storage_dir: str, timeout_hours: int = 72):
        self.adapter = adapter
        self.storage_dir = Path(storage_dir)
        self.timeout_hours = timeout_hours

    async def try_collect(self, boss_id: str, slot: IntakeSlot) -> tuple[str | None, CollectStatus]:
        try:
            received = await self.adapter.list_received_resumes()
        except Exception as e:
            logger.error(f"list_received_resumes failed: {e}")
            return None, "error"

        for bx, url in received:
            if bx == boss_id:
                self.storage_dir.mkdir(parents=True, exist_ok=True)
                save_path = str(self.storage_dir / f"{boss_id}.pdf")
                try:
                    ok = await self.adapter.download_pdf(url, save_path)
                except Exception as e:
                    logger.error(f"download_pdf failed [{boss_id}]: {e}")
                    return None, "error"
                if ok:
                    return save_path, "received"

        if slot.ask_count == 0:
            try:
                ok = await self.adapter.click_request_resume(boss_id)
            except Exception as e:
                logger.error(f"click_request_resume failed: {e}")
                return None, "error"
            return None, "requested" if ok else "error"

        if slot.asked_at is not None:
            asked = slot.asked_at if slot.asked_at.tzinfo else slot.asked_at.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - asked > timedelta(hours=self.timeout_hours):
                return None, "abandon"

        return None, "waiting"
