from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock
from app.modules.im_intake.decision import decide_next_action, NextAction


def _slot(key, value=None, ask_count=0, asked_at=None, category="hard"):
    s = MagicMock()
    s.slot_key, s.value, s.ask_count, s.asked_at, s.slot_category = key, value, ask_count, asked_at, category
    return s


def test_send_hard_when_all_empty():
    slots = [_slot("arrival_date"), _slot("free_slots"), _slot("intern_duration"),
             _slot("pdf", value="p.pdf", category="pdf")]
    cand = MagicMock(name="张三"); job = MagicMock(title="前端", competency_model=None)
    action = decide_next_action(cand, slots, job, hard_max=3, pdf_timeout_h=72)
    assert action.type == "send_hard"
    assert "arrival_date" in action.meta["slot_keys"]
    assert "想跟您先确认" in action.text


def test_request_pdf_when_pdf_never_asked():
    slots = [_slot("arrival_date", value="下周一"), _slot("free_slots", value="周三下午"),
             _slot("intern_duration", value="6个月"), _slot("pdf", category="pdf")]
    cand = MagicMock(); job = MagicMock(competency_model=None)
    action = decide_next_action(cand, slots, job, hard_max=3, pdf_timeout_h=72)
    assert action.type == "request_pdf"


def test_wait_pdf_within_timeout():
    now = datetime.now(timezone.utc)
    slots = [_slot("arrival_date", value="x"), _slot("free_slots", value="x"),
             _slot("intern_duration", value="x"),
             _slot("pdf", ask_count=1, asked_at=now - timedelta(hours=10), category="pdf")]
    job = MagicMock(competency_model=None)
    action = decide_next_action(MagicMock(), slots, job, 3, 72)
    assert action.type == "wait_pdf"


def test_abandon_pdf_expired():
    past = datetime.now(timezone.utc) - timedelta(hours=80)
    slots = [_slot("arrival_date", value="x"), _slot("free_slots", value="x"),
             _slot("intern_duration", value="x"),
             _slot("pdf", ask_count=1, asked_at=past, category="pdf")]
    action = decide_next_action(MagicMock(), slots, MagicMock(competency_model=None), 3, 72)
    assert action.type == "abandon"


def test_mark_pending_human_when_hard_exhausted_pdf_done():
    slots = [_slot("arrival_date", ask_count=3), _slot("free_slots", value="x"),
             _slot("intern_duration", value="x"), _slot("pdf", value="p.pdf", category="pdf")]
    action = decide_next_action(MagicMock(), slots, MagicMock(competency_model=None), 3, 72)
    assert action.type == "mark_pending_human"


def test_complete_when_all_filled_no_soft_needed():
    slots = [_slot("arrival_date", value="x"), _slot("free_slots", value="x"),
             _slot("intern_duration", value="x"), _slot("pdf", value="p.pdf", category="pdf")]
    action = decide_next_action(MagicMock(), slots, MagicMock(competency_model=None), 3, 72)
    assert action.type == "complete"


def test_send_soft_when_hard_filled_and_competency_model_exists():
    slots = [_slot("arrival_date", value="x"), _slot("free_slots", value="x"),
             _slot("intern_duration", value="x"), _slot("pdf", value="p.pdf", category="pdf")]
    job = MagicMock(competency_model={"assessment_dimensions": [{"name": "技术深度"}]})
    action = decide_next_action(MagicMock(), slots, job, 3, 72)
    assert action.type == "send_soft"


def test_complete_when_soft_already_sent():
    slots = [_slot("arrival_date", value="x"), _slot("free_slots", value="x"),
             _slot("intern_duration", value="x"), _slot("pdf", value="p.pdf", category="pdf"),
             _slot("soft_q_1", ask_count=1, category="soft")]
    job = MagicMock(competency_model={"assessment_dimensions": [{"name": "技术深度"}]})
    action = decide_next_action(MagicMock(), slots, job, 3, 72)
    assert action.type == "complete"
