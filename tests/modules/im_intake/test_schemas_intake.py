import pytest
from pydantic import ValidationError
from app.modules.im_intake.schemas import (
    ChatMessageIn, CollectChatIn, NextActionOut, AckSentIn, StartConversationOut,
)


def test_collect_chat_in_requires_boss_id_and_messages():
    m = ChatMessageIn(sender_id="bx1", content="hi", sent_at="2026-04-22T10:00:00Z")
    payload = CollectChatIn(boss_id="bx1", name="张三", job_intention="前端实习", messages=[m])
    assert payload.boss_id == "bx1"
    assert len(payload.messages) == 1


def test_collect_chat_in_rejects_empty_boss_id():
    with pytest.raises(ValidationError):
        CollectChatIn(boss_id="", messages=[])


def test_next_action_out_serializes():
    a = NextActionOut(type="send_hard", text="您好~...", slot_keys=["arrival_date"])
    d = a.model_dump()
    assert d["type"] == "send_hard"


def test_ack_sent_requires_action_type():
    AckSentIn(action_type="send_hard", delivered=True)
    with pytest.raises(ValidationError):
        AckSentIn(delivered=True)


def test_start_conversation_out_has_deep_link():
    o = StartConversationOut(candidate_id=1, boss_id="bx1", deep_link="https://www.zhipin.com/web/chat/index?id=bx1")
    assert "zhipin.com" in o.deep_link
