import asyncio
import logging
from datetime import datetime
from typing import Callable
from app.adapters.boss.base import BossAdapter
from app.config import settings

logger = logging.getLogger(__name__)


class IntakeScheduler:
    def __init__(self, adapter: BossAdapter, service_factory: Callable, batch_cap: int = 50):
        self.adapter = adapter
        self.service_factory = service_factory
        self.batch_cap = batch_cap
        self._lock = asyncio.Lock()
        self.running = True
        self.next_run_at: datetime | None = None
        self.last_batch_size: int = 0

    async def tick(self) -> None:
        if not self.running:
            return
        if self._lock.locked():
            logger.info("IntakeScheduler.tick: lock held, skipping")
            self.last_batch_size = 0
            return
        async with self._lock:
            try:
                candidates = await self.adapter.list_chat_index()
            except Exception as e:
                logger.error(f"list_chat_index failed: {e}")
                self.last_batch_size = 0
                return
            cap_remaining = settings.boss_max_operations_per_day - getattr(self.adapter, "_operations_today", 0)
            n = min(len(candidates), self.batch_cap, max(0, cap_remaining))
            self.last_batch_size = n
            for c in candidates[:n]:
                svc = self.service_factory()
                try:
                    await svc.process_one(c)
                except Exception as e:
                    logger.error(f"process_one failed [{c.boss_id}]: {e}")

    def pause(self) -> None:
        self.running = False

    def resume(self) -> None:
        self.running = True

    async def tick_now(self) -> None:
        await self.tick()
