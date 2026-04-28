"""F3.1 T8 — POST /api/intake/collect-chat tests."""
from app.modules.im_intake.models import IntakeSlot


def test_collect_chat_creates_candidate_and_returns_next_action(client, db_session):
    payload = {
        "boss_id": "bxTest1",
        "name": "测试张三",
        "job_intention": "前端实习",
        "messages": [{"sender_id": "bxTest1", "content": "你好"}],
    }
    r = client.post("/api/intake/collect-chat", json=payload)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["candidate_id"] > 0
    assert data["intake_status"] in ("collecting", "awaiting_reply", "complete")
    assert data["next_action"]["type"] in (
        "send_hard", "request_pdf", "complete", "wait_pdf",
        "send_soft", "mark_pending_human", "abandon",
    )


def test_collect_chat_idempotent_on_boss_id(client, db_session):
    p = {"boss_id": "bxDup", "messages": []}
    r1 = client.post("/api/intake/collect-chat", json=p)
    r1.raise_for_status()
    r2 = client.post("/api/intake/collect-chat", json=p)
    r2.raise_for_status()
    assert r1.json()["candidate_id"] == r2.json()["candidate_id"]


def test_collect_chat_fills_slots_from_messages(client, db_session):
    """Slot extractor returns the candidate's original message content
    verbatim — no rewriting / phrase carving — so the UI shows what the
    candidate actually said.
    """
    msg = "明天到岗，能实习半年"
    payload = {
        "boss_id": "bxParse",
        "messages": [{"sender_id": "bxParse", "content": msg}],
    }
    r = client.post("/api/intake/collect-chat", json=payload)
    assert r.status_code == 200, r.text
    cid = r.json()["candidate_id"]
    slots = {s.slot_key: s for s in db_session.query(IntakeSlot).filter_by(candidate_id=cid).all()}
    # Both slots quote the same source message; we keep the full sentence
    # rather than carving "明天" / "半年" out of it.
    assert slots["arrival_date"].value == msg
    assert slots["intern_duration"].value == msg
