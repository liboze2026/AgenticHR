import json
from unittest.mock import AsyncMock
import pytest
from app.modules.im_intake.slot_filler import SlotFiller


BOSS_ID = "93213195-0"


def _msgs(*pairs):
    return [{"sender_id": sid, "content": c} for sid, c in pairs]


@pytest.mark.asyncio
async def test_returns_empty_without_llm():
    f = SlotFiller(llm=None)
    result = await f.parse_conversation(
        _msgs((BOSS_ID, "本周内到岗")), BOSS_ID, ["arrival_date"],
    )
    assert result == {}


@pytest.mark.asyncio
async def test_llm_returns_raw_candidate_phrase():
    llm = AsyncMock()
    llm.complete.return_value = json.dumps({
        "arrival_date": "本周内到岗",
        "intern_duration": None,
        "free_slots": "4月25下午6点有时间 | 明天晚上没空，其他时候都有",
    })
    f = SlotFiller(llm=llm)
    result = await f.parse_conversation(
        _msgs(
            (BOSS_ID, "您好，岗位有兴趣"),
            ("self", "什么时候到岗？面试时段？"),
            (BOSS_ID, "本周内到岗，我明天晚上没空，其他时候都有"),
        ),
        BOSS_ID,
        ["arrival_date", "intern_duration", "free_slots"],
    )
    llm.complete.assert_called_once()
    assert result["arrival_date"] == ("本周内到岗", "llm")
    assert "intern_duration" not in result
    assert result["free_slots"] == ("4月25下午6点有时间 | 明天晚上没空，其他时候都有", "llm")


@pytest.mark.asyncio
async def test_hr_lines_not_attributed_to_candidate():
    """Prompt must label HR lines as HR; LLM shouldn't treat HR questions as candidate statements."""
    llm = AsyncMock()
    llm.complete.return_value = json.dumps({"arrival_date": None})
    f = SlotFiller(llm=llm)
    await f.parse_conversation(
        _msgs(
            ("self", "您最快什么时候到岗？下周一可以吗？"),  # HR, not candidate
            (BOSS_ID, "我再看看"),
        ),
        BOSS_ID,
        ["arrival_date"],
    )
    prompt_text = llm.complete.call_args.kwargs["messages"][0]["content"]
    assert "HR: 您最快什么时候到岗" in prompt_text
    assert "候选人: 我再看看" in prompt_text


@pytest.mark.asyncio
async def test_invalid_json_returns_empty():
    llm = AsyncMock()
    llm.complete.return_value = "not json"
    f = SlotFiller(llm=llm)
    result = await f.parse_conversation(
        _msgs((BOSS_ID, "随便")), BOSS_ID, ["arrival_date"],
    )
    assert result == {}


@pytest.mark.asyncio
async def test_list_values_joined():
    llm = AsyncMock()
    llm.complete.return_value = json.dumps({
        "free_slots": ["周一上午", "周三下午"],
    })
    f = SlotFiller(llm=llm)
    result = await f.parse_conversation(
        _msgs((BOSS_ID, "周一上午和周三下午都可以")),
        BOSS_ID, ["free_slots"],
    )
    assert result["free_slots"] == ("周一上午 | 周三下午", "llm")


@pytest.mark.asyncio
async def test_empty_messages_skips_llm():
    llm = AsyncMock()
    f = SlotFiller(llm=llm)
    result = await f.parse_conversation([], BOSS_ID, ["arrival_date"])
    assert result == {}
    llm.complete.assert_not_called()
