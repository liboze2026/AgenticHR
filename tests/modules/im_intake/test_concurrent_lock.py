import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest
from app.modules.im_intake.scheduler import IntakeScheduler


@pytest.mark.asyncio
async def test_f4_skips_when_external_holder_uses_adapter():
    adapter = AsyncMock()
    adapter.list_chat_index = AsyncMock(return_value=[MagicMock(boss_id="x")])
    adapter._operations_today = 0
    sched = IntakeScheduler(adapter=adapter, service_factory=MagicMock(), batch_cap=10)

    await sched._lock.acquire()  # simulate F3 holding
    try:
        await sched.tick()
    finally:
        sched._lock.release()
    assert sched.last_batch_size == 0
    adapter.list_chat_index.assert_not_called()
