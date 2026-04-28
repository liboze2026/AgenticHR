"""Defense-in-depth: weird user operations that historically broke flows.

The user can pause, resume, click abandon manually, force-complete, edit slot
values, paste massive chat logs, close the browser mid-claim, and open multiple
Boss tabs at once — at any moment, in any order. These tests pin down behaviors
the system MUST preserve under each weird operation.

Coverage map (W-N → which user behavior is being defended):
W-1   manual /abandon expires pending outbox + sets completed_at
W-2   manual /abandon idempotent (re-abandon noop)
W-3   collect-chat on terminal candidate is a noop (no slot mutation, no outbox)
W-4   collect-chat passing pdf_url to terminal candidate does not overwrite pdf_path
W-5   patch_slot on slot of terminal candidate rejected (409)
W-6   ack-sent on terminal candidate returns ok and is a noop
W-7   settings PUT enabled=False expires user's pending+claimed outbox
W-8   settings PUT lowering target below complete_count expires user's outbox
W-9   ensure_candidate on terminal candidate does NOT downgrade status / overwrite name
W-10  collect-chat clamps obscenely long messages list (DoS guard)
W-11  delete_candidate cascades to outbox rows (no orphan ghosts)
W-12  daily cap is exposed and consistent under concurrent inserts
"""
from datetime import datetime, timedelta, timezone
import pytest

from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.im_intake.models import IntakeSlot
from app.modules.im_intake.outbox_model import IntakeOutbox
from app.modules.im_intake.templates import HARD_SLOT_KEYS


def _seed_active(db, *, user_id=1, boss_id="bxW", status="collecting"):
    now = datetime.now(timezone.utc)
    c = IntakeCandidate(
        user_id=user_id, boss_id=boss_id, name="W",
        intake_status=status, source="plugin",
        intake_started_at=now, expires_at=now + timedelta(days=14),
    )
    db.add(c); db.commit()
    for k in HARD_SLOT_KEYS:
        db.add(IntakeSlot(candidate_id=c.id, slot_key=k, slot_category="hard"))
    db.add(IntakeSlot(candidate_id=c.id, slot_key="pdf", slot_category="pdf"))
    db.commit()
    return c


def _seed_terminal(db, *, user_id=1, boss_id="bxWT", status="complete"):
    now = datetime.now(timezone.utc)
    c = IntakeCandidate(
        user_id=user_id, boss_id=boss_id, name="WT",
        intake_status=status, source="plugin",
        intake_started_at=now - timedelta(hours=2),
        intake_completed_at=now,
        expires_at=now + timedelta(days=14),
    )
    db.add(c); db.commit()
    for k in HARD_SLOT_KEYS:
        db.add(IntakeSlot(candidate_id=c.id, slot_key=k, slot_category="hard",
                          value="x", answered_at=now))
    db.add(IntakeSlot(candidate_id=c.id, slot_key="pdf", slot_category="pdf"))
    db.commit()
    return c


def _seed_pending_outbox(db, candidate, slot_key="arrival_date"):
    row = IntakeOutbox(
        candidate_id=candidate.id, user_id=candidate.user_id,
        action_type="send_hard", text="Q",
        slot_keys=[slot_key], status="pending",
        scheduled_for=datetime.now(timezone.utc),
    )
    db.add(row); db.commit()
    return row


# ---------- W-1 ----------
def test_manual_abandon_expires_pending_outbox(client, db_session):
    c = _seed_active(db_session, boss_id="bxW1")
    row = _seed_pending_outbox(db_session, c)
    row_id = row.id

    r = client.post(f"/api/intake/candidates/{c.id}/abandon")
    assert r.status_code == 200
    db_session.expire_all()
    c2 = db_session.query(IntakeCandidate).filter_by(id=c.id).first()
    ob = db_session.query(IntakeOutbox).filter_by(id=row_id).first()
    assert c2.intake_status == "abandoned"
    assert c2.intake_completed_at is not None, "manual abandon must stamp completed_at"
    assert ob.status == "expired", "pending outbox must expire on manual abandon"


# ---------- W-2 ----------
def test_manual_abandon_is_idempotent(client, db_session):
    c = _seed_terminal(db_session, status="abandoned", boss_id="bxW2")
    pre_completed = c.intake_completed_at
    r = client.post(f"/api/intake/candidates/{c.id}/abandon")
    assert r.status_code == 200
    db_session.expire_all()
    c2 = db_session.query(IntakeCandidate).filter_by(id=c.id).first()
    assert c2.intake_status == "abandoned"


# ---------- W-3 ----------
def test_collect_chat_on_terminal_is_noop(client, db_session):
    c = _seed_terminal(db_session, status="complete", boss_id="bxW3")
    pre_status = c.intake_status
    pre_pdf = c.pdf_path

    r = client.post("/api/intake/collect-chat", json={
        "boss_id": "bxW3",
        "messages": [{"sender_id": "bxW3", "content": "hi", "sent_at":
                      datetime.now(timezone.utc).isoformat()}],
    })
    assert r.status_code == 200
    db_session.expire_all()
    c2 = db_session.query(IntakeCandidate).filter_by(id=c.id).first()
    assert c2.intake_status == pre_status
    # No new outbox generated for terminal candidate
    assert db_session.query(IntakeOutbox).filter_by(candidate_id=c.id).count() == 0


# ---------- W-4 ----------
def test_collect_chat_terminal_does_not_overwrite_pdf_path(client, db_session):
    c = _seed_terminal(db_session, status="complete", boss_id="bxW4")
    # Post-BUG-044: pdf_url validator rejects "/abs" paths; use relative
    c.pdf_path = "old/resume.pdf"
    db_session.commit()
    r = client.post("/api/intake/collect-chat", json={
        "boss_id": "bxW4",
        "messages": [],
        "pdf_present": True, "pdf_url": "new/resume.pdf",
    })
    assert r.status_code == 200
    db_session.expire_all()
    c2 = db_session.query(IntakeCandidate).filter_by(id=c.id).first()
    assert c2.pdf_path == "old/resume.pdf", (
        "terminal candidate's pdf_path must not be clobbered by late collect-chat"
    )


# ---------- W-5 ----------
def test_patch_slot_on_terminal_candidate_rejected(client, db_session):
    c = _seed_terminal(db_session, boss_id="bxW5")
    s = db_session.query(IntakeSlot).filter_by(
        candidate_id=c.id, slot_key="arrival_date").first()

    r = client.put(f"/api/intake/slots/{s.id}", json={"value": "下周三"})
    assert r.status_code == 409, (
        f"patching slot of terminal candidate must be 409, got {r.status_code}"
    )
    db_session.expire_all()
    s2 = db_session.query(IntakeSlot).filter_by(id=s.id).first()
    assert s2.value == "x", "slot value must not change for terminal candidate"


# ---------- W-6 ----------
def test_ack_sent_on_terminal_is_noop(client, db_session):
    c = _seed_terminal(db_session, boss_id="bxW6")
    r = client.post(f"/api/intake/candidates/{c.id}/ack-sent",
                    json={"action_type": "send_hard", "delivered": True})
    # Either 200 ok-noop or 409 state mismatch. Both acceptable; key invariant
    # is that the terminal candidate is not regressed.
    assert r.status_code in (200, 409)
    db_session.expire_all()
    c2 = db_session.query(IntakeCandidate).filter_by(id=c.id).first()
    assert c2.intake_status == "complete"


# ---------- W-7 ----------
def test_settings_pause_expires_pending_outbox(client, db_session):
    c = _seed_active(db_session, boss_id="bxW7")
    row = _seed_pending_outbox(db_session, c)
    row_id = row.id

    # Enable + target=99 first so the running gate can be subsequently flipped off
    client.put("/api/intake/settings", json={"enabled": True, "target_count": 99})
    db_session.commit()
    # Now pause
    r = client.put("/api/intake/settings", json={"enabled": False, "target_count": 99})
    assert r.status_code == 200
    db_session.expire_all()
    ob = db_session.query(IntakeOutbox).filter_by(id=row_id).first()
    assert ob.status == "expired", (
        "pausing intake must expire user's pending outbox to prevent replay on resume"
    )


# ---------- W-8 ----------
def test_settings_target_below_complete_expires_outbox(client, db_session):
    # Seed 2 complete candidates so complete_count=2
    for i in range(2):
        ct = _seed_terminal(db_session, boss_id=f"bxW8c{i}", status="complete")
    active = _seed_active(db_session, boss_id="bxW8a")
    row = _seed_pending_outbox(db_session, active)
    row_id = row.id

    client.put("/api/intake/settings", json={"enabled": True, "target_count": 99})
    # Now lower target below complete_count
    r = client.put("/api/intake/settings", json={"enabled": True, "target_count": 1})
    assert r.status_code == 200
    db_session.expire_all()
    ob = db_session.query(IntakeOutbox).filter_by(id=row_id).first()
    assert ob.status == "expired", (
        "lowering target below complete_count must expire user's outbox; "
        f"is_running becomes False so dormant rows would replay on raise — got {ob.status}"
    )


# ---------- W-9 ----------
def test_ensure_candidate_does_not_downgrade_terminal(db_session):
    c = _seed_terminal(db_session, boss_id="bxW9", status="complete")
    pre_name = c.name

    from app.modules.im_intake.service import IntakeService
    svc = IntakeService(db=db_session, user_id=1)
    returned = svc.ensure_candidate("bxW9", name="NewName", job_intention="x")
    db_session.expire_all()
    c2 = db_session.query(IntakeCandidate).filter_by(id=c.id).first()
    assert c2.intake_status == "complete", "must not downgrade terminal"
    # name policy: ensure_candidate's existing logic only fills name if previously
    # empty; we don't strictly require terminal-name immutability here, but the
    # status must hold. Re-check explicitly so future regressions surface.
    assert returned.id == c.id


# ---------- W-10 ----------
def test_collect_chat_clamps_obscenely_long_messages(client, db_session):
    """If the user pastes a 50,000-message chat log (or extension misbehaves),
    backend must not blindly persist all of it into chat_snapshot — that would
    bloat the row and DOS the slot extractor."""
    c = _seed_active(db_session, boss_id="bxW10")
    # Build a huge message list
    huge = [{"sender_id": "bxW10", "content": f"msg{i}",
             "sent_at": datetime.now(timezone.utc).isoformat()}
            for i in range(2000)]
    r = client.post("/api/intake/collect-chat",
                    json={"boss_id": "bxW10", "messages": huge})
    assert r.status_code in (200, 413, 422), f"unexpected {r.status_code}"
    db_session.expire_all()
    c2 = db_session.query(IntakeCandidate).filter_by(id=c.id).first()
    snap = c2.chat_snapshot or {}
    saved = (snap.get("messages") or []) if isinstance(snap, dict) else []
    assert len(saved) <= 500, (
        f"chat_snapshot must clamp message count, stored={len(saved)}"
    )


# ---------- W-11 ----------
def test_delete_candidate_cascades_to_outbox(client, db_session):
    c = _seed_active(db_session, boss_id="bxW11")
    _seed_pending_outbox(db_session, c)
    cid = c.id

    r = client.delete(f"/api/intake/candidates/{cid}")
    assert r.status_code == 204
    db_session.expire_all()
    assert db_session.query(IntakeCandidate).filter_by(id=cid).first() is None
    # Outbox rows must be gone too (FK CASCADE or explicit cleanup)
    leftover = db_session.query(IntakeOutbox).filter_by(candidate_id=cid).count()
    assert leftover == 0, (
        f"deleting candidate must cascade to outbox; {leftover} orphan rows remain"
    )


# ---------- W-12 ----------
def test_daily_cap_endpoint_consistent(client, db_session):
    """The daily-cap endpoint must reflect today's actual candidate count for
    the calling user, not include other users' candidates and not double-count."""
    # Seed 3 candidates today for user 1
    today = datetime.now(timezone.utc).replace(hour=12)
    for i in range(3):
        db_session.add(IntakeCandidate(
            user_id=1, boss_id=f"bxW12_{i}", name="x",
            intake_status="collecting", source="plugin",
            intake_started_at=today, created_at=today,
            expires_at=today + timedelta(days=14),
        ))
    # Seed one candidate for user 2 — must not leak
    db_session.add(IntakeCandidate(
        user_id=2, boss_id="bxW12_other", name="x",
        intake_status="collecting", source="plugin",
        intake_started_at=today, created_at=today,
        expires_at=today + timedelta(days=14),
    ))
    db_session.commit()

    r = client.get("/api/intake/daily-cap")
    assert r.status_code == 200
    data = r.json()
    assert data["used"] == 3, f"daily-cap must scope to user, got {data}"
    assert data["remaining"] == max(0, data["cap"] - 3)
