import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest
from app.modules.im_intake.scheduler import IntakeScheduler


@pytest.mark.asyncio
async def test_tick_skips_when_already_locked():
    sched = IntakeScheduler(adapter=AsyncMock(), service_factory=MagicMock(), batch_cap=10)
    await sched._lock.acquire()
    try:
        await sched.tick()
    finally:
        sched._lock.release()
    assert sched.last_batch_size == 0


@pytest.mark.asyncio
async def test_tick_processes_up_to_batch_cap():
    adapter = AsyncMock()
    adapter.list_chat_index = AsyncMock(return_value=[
        MagicMock(boss_id=f"id{i}") for i in range(10)
    ])
    adapter._operations_today = 0
    svc = AsyncMock()
    svc.process_one = AsyncMock()
    factory = MagicMock(return_value=svc)
    sched = IntakeScheduler(adapter=adapter, service_factory=factory, batch_cap=3)
    await sched.tick()
    assert svc.process_one.call_count == 3
    assert sched.last_batch_size == 3


@pytest.mark.asyncio
async def test_pause_resume():
    sched = IntakeScheduler(adapter=AsyncMock(), service_factory=MagicMock(), batch_cap=1)
    sched.pause(); assert not sched.running
    sched.resume(); assert sched.running
