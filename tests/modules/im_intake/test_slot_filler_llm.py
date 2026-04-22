import json
from unittest.mock import AsyncMock
import pytest
from app.modules.im_intake.slot_filler import SlotFiller


@pytest.mark.asyncio
async def test_llm_called_when_regex_misses():
    llm = AsyncMock()
    llm.complete.return_value = json.dumps({
        "arrival_date": "下周二",
        "intern_duration": None,
        "free_slots": [],
    })
    f = SlotFiller(llm=llm)
    result = await f.parse_reply(
        reply_text="可能那时候吧",
        pending_slot_keys=["arrival_date", "intern_duration", "free_slots"],
    )
    llm.complete.assert_called_once()
    assert result["arrival_date"] == ("下周二", "llm")
    assert "intern_duration" not in result
    assert "free_slots" not in result


@pytest.mark.asyncio
async def test_regex_short_circuits_llm():
    llm = AsyncMock()
    f = SlotFiller(llm=llm)
    result = await f.parse_reply("我下周一入职", pending_slot_keys=["arrival_date"])
    llm.complete.assert_not_called()
    assert result["arrival_date"] == ("下周一", "regex")


@pytest.mark.asyncio
async def test_llm_invalid_json_returns_empty():
    llm = AsyncMock()
    llm.complete.return_value = "not json"
    f = SlotFiller(llm=llm)
    result = await f.parse_reply("乱说", pending_slot_keys=["arrival_date"])
    assert result == {}
