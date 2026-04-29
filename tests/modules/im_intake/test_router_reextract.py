"""POST /api/intake/candidates/{id}/reextract tests"""
import pytest
from unittest.mock import patch, AsyncMock


def _seed(db_session, boss_id="bxRe", messages=None, fill_slots=("",)):
    from app.modules.im_intake.candidate_model import IntakeCandidate
    from app.modules.im_intake.models import IntakeSlot
    snapshot = {"messages": messages} if messages is not None else None
    c = IntakeCandidate(
        user_id=1, boss_id=boss_id, name="重抽测试",
        intake_status="awaiting_reply", source="plugin",
        chat_snapshot=snapshot,
    )
    db_session.add(c)
    db_session.commit()
    db_session.refresh(c)
    for k in ("arrival_date", "free_slots", "intern_duration", "pdf"):
        db_session.add(IntakeSlot(
            candidate_id=c.id, slot_key=k,
            slot_category="hard" if k != "pdf" else "pdf",
            value="",
            ask_count=2 if k != "pdf" else 0,
        ))
    db_session.commit()
    return c


def test_reextract_no_messages_skipped(client, db_session):
    c = _seed(db_session, boss_id="bxNoMsg", messages=[])
    r = client.post(f"/api/intake/candidates/{c.id}/reextract")
    assert r.status_code == 200
    body = r.json()
    assert body["filled"] == []
    assert body["skipped"] == "no_messages"


def test_reextract_unknown_candidate_404(client):
    r = client.post("/api/intake/candidates/99999/reextract")
    assert r.status_code == 404


def test_reextract_user_scoping(client, db_session):
    """User 2's candidate not visible to user 1"""
    from app.modules.im_intake.candidate_model import IntakeCandidate
    c = IntakeCandidate(user_id=2, boss_id="bxOther", name="他人",
                        intake_status="collecting", source="plugin")
    db_session.add(c); db_session.commit()
    r = client.post(f"/api/intake/candidates/{c.id}/reextract")
    assert r.status_code == 404


def test_reextract_all_filled_skipped(client, db_session):
    from app.modules.im_intake.candidate_model import IntakeCandidate
    from app.modules.im_intake.models import IntakeSlot
    c = IntakeCandidate(user_id=1, boss_id="bxAll", name="已齐",
                        intake_status="awaiting_reply", source="plugin",
                        chat_snapshot={"messages": [{"sender_id": "bxAll", "content": "x"}]})
    db_session.add(c); db_session.commit(); db_session.refresh(c)
    for k in ("arrival_date", "free_slots", "intern_duration"):
        db_session.add(IntakeSlot(
            candidate_id=c.id, slot_key=k, slot_category="hard",
            value="filled", ask_count=1,
        ))
    db_session.commit()
    r = client.post(f"/api/intake/candidates/{c.id}/reextract")
    assert r.status_code == 200
    assert r.json()["skipped"] == "all_hard_filled"


def test_reextract_fills_pending_slots_from_llm(client, db_session, monkeypatch):
    """LLM 返回 indices, 后端写入 slot value"""
    msgs = [
        {"sender_id": "bxFill", "content": "可全职稳定实习 12 个月"},
    ]
    c = _seed(db_session, boss_id="bxFill", messages=msgs)

    fake_llm_response = '{"arrival_date": [], "free_slots": [], "intern_duration": [0]}'

    class FakeLLM:
        async def complete(self, messages, **kw):
            return fake_llm_response

    from app import main as _main
    monkeypatch.setattr(_main, "llm_client", FakeLLM())

    r = client.post(f"/api/intake/candidates/{c.id}/reextract")
    assert r.status_code == 200
    body = r.json()
    assert "intern_duration" in body["filled"]

    from app.modules.im_intake.models import IntakeSlot
    slot = db_session.query(IntakeSlot).filter_by(
        candidate_id=c.id, slot_key="intern_duration"
    ).first()
    assert "实习 12 个月" in slot.value


def test_reextract_no_llm_returns_503(client, db_session, monkeypatch):
    msgs = [{"sender_id": "bxNoLLM", "content": "随便"}]
    c = _seed(db_session, boss_id="bxNoLLM", messages=msgs)

    from app import main as _main
    monkeypatch.setattr(_main, "llm_client", None)

    r = client.post(f"/api/intake/candidates/{c.id}/reextract")
    assert r.status_code == 503
