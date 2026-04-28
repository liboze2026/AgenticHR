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
async def test_llm_returns_message_indices_and_filler_quotes_originals():
    """LLM picks message indices; SlotFiller reconstructs slot value from
    the candidate's verbatim message content (no rewriting, no carving).
    """
    llm = AsyncMock()
    # Index map for the conversation below:
    #   [#0] 候选人: 您好，岗位有兴趣
    #   [#1] HR:    什么时候到岗？面试时段？
    #   [#2] 候选人: 本周内到岗，我明天晚上没空，其他时候都有
    llm.complete.return_value = json.dumps({
        "arrival_date": [2],
        "intern_duration": None,
        "free_slots": [2],
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
    msg = "本周内到岗，我明天晚上没空，其他时候都有"
    assert result["arrival_date"] == (msg, "llm")
    assert "intern_duration" not in result
    assert result["free_slots"] == (msg, "llm")


@pytest.mark.asyncio
async def test_hr_message_index_is_dropped_even_if_llm_picks_it():
    """If the LLM mistakenly picks an HR message index, we must NOT surface
    HR words as the candidate's slot value — only candidate-message indices
    are recoverable."""
    llm = AsyncMock()
    llm.complete.return_value = json.dumps({"arrival_date": [0]})  # index 0 is HR
    f = SlotFiller(llm=llm)
    result = await f.parse_conversation(
        _msgs(
            ("self", "您最快什么时候到岗？"),  # HR message at #0
            (BOSS_ID, "我再看看"),             # candidate at #1
        ),
        BOSS_ID,
        ["arrival_date"],
    )
    assert result == {}


@pytest.mark.asyncio
async def test_multiple_candidate_messages_joined_with_newline():
    """When the LLM picks multiple candidate messages, the slot value
    contains all of them in order, deduplicated, joined by newline."""
    llm = AsyncMock()
    llm.complete.return_value = json.dumps({"free_slots": [0, 2]})
    f = SlotFiller(llm=llm)
    result = await f.parse_conversation(
        _msgs(
            (BOSS_ID, "周二下午可以"),     # #0
            ("self", "周三呢？"),            # #1 HR
            (BOSS_ID, "周三晚上不行"),     # #2
        ),
        BOSS_ID, ["free_slots"],
    )
    assert result["free_slots"] == ("周二下午可以\n周三晚上不行", "llm")


@pytest.mark.asyncio
async def test_hr_lines_not_attributed_to_candidate():
    """Prompt must label HR lines as HR; LLM shouldn't treat HR questions
    as candidate statements. Each line is also numbered [#i] so the LLM
    can refer to messages by index."""
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
    assert "[#0] HR: 您最快什么时候到岗" in prompt_text
    assert "[#1] 候选人: 我再看看" in prompt_text


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
async def test_index_list_resolves_to_candidate_quote():
    """Index-list responses look up the candidate's verbatim message text;
    repeated indices are deduplicated."""
    llm = AsyncMock()
    llm.complete.return_value = json.dumps({"free_slots": [0, 0]})
    f = SlotFiller(llm=llm)
    result = await f.parse_conversation(
        _msgs((BOSS_ID, "周一上午和周三下午都可以")),
        BOSS_ID, ["free_slots"],
    )
    assert result["free_slots"] == ("周一上午和周三下午都可以", "llm")


@pytest.mark.asyncio
async def test_empty_messages_skips_llm():
    llm = AsyncMock()
    f = SlotFiller(llm=llm)
    result = await f.parse_conversation([], BOSS_ID, ["arrival_date"])
    assert result == {}
    llm.complete.assert_not_called()
