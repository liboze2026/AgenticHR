"""chaos-qa-hunter Round 2: state machine + logic + error path attacks."""
import pytest
from datetime import datetime, timezone, timedelta


def collect(client, boss_id="b1", messages=None, skip_outbox=True, **kw):
    body = {"boss_id": boss_id, "messages": messages or [], "skip_outbox": skip_outbox}
    body.update(kw)
    return client.post("/api/intake/collect-chat", json=body)


def enable(client, target=100):
    client.put("/api/intake/settings", json={"enabled": True, "target_count": target})


# ══════════════════════════════════════════════════════════════════════════════
# ATTACK B1: collect-chat with pdf_present=True but pdf_url=None
# ══════════════════════════════════════════════════════════════════════════════
def test_B1_pdf_present_but_no_url(client):
    """BUG-053 fix: pdf_present=True without pdf_url rejected at validation."""
    r = collect(client, boss_id="pdf_no_url", pdf_present=True, pdf_url=None)
    assert r.status_code == 422


# ══════════════════════════════════════════════════════════════════════════════
# ATTACK B2: autoscan/tick missing "processed" key entirely
# ══════════════════════════════════════════════════════════════════════════════
def test_B2_autoscan_tick_missing_processed(client):
    """autoscan/tick with completely missing processed key.
    int(body.get('processed', 0)) → int(0) = 0 → should be fine."""
    r = client.post("/api/intake/autoscan/tick", json={})
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text[:200]}"


def test_B2b_autoscan_tick_float_processed(client):
    """BUG-045 fix: AutoScanTickIn coerces lossless ints; non-lossless floats reject.

    Pydantic v2 default int coerces 3.0→3 but rejects 3.7. Either behavior is
    safe (no crash); just assert the response is structured (200 or 422),
    not 500.
    """
    r = client.post("/api/intake/autoscan/tick",
                    json={"processed": 3.7, "skipped": 1.2, "total": 5.9})
    assert r.status_code in (200, 422)


def test_B2c_autoscan_tick_none_processed(client):
    """BUG-051 fix: null processed rejected by Pydantic schema, not 500."""
    r = client.post("/api/intake/autoscan/tick", json={"processed": None})
    assert r.status_code == 422


# ══════════════════════════════════════════════════════════════════════════════
# ATTACK B3: ack-sent on candidate where action_type doesn't match
# ══════════════════════════════════════════════════════════════════════════════
def test_B3_ack_sent_action_type_mismatch(client, db_session):
    """Extension sends 'request_pdf' but acks as 'send_hard' — state drift path."""
    from app.modules.im_intake.candidate_model import IntakeCandidate
    from app.modules.im_intake.models import IntakeSlot
    from app.modules.im_intake.templates import HARD_SLOT_KEYS
    c = IntakeCandidate(user_id=1, boss_id="mismatch_b", name="M",
                        intake_status="collecting", source="plugin")
    db_session.add(c); db_session.commit()
    for k in HARD_SLOT_KEYS:
        db_session.add(IntakeSlot(candidate_id=c.id, slot_key=k, slot_category="hard"))
    db_session.add(IntakeSlot(candidate_id=c.id, slot_key="pdf", slot_category="pdf"))
    db_session.commit()

    # BUG-052 fix: state drift on ack-sent now returns 409 instead of 200
    r = client.post(f"/api/intake/candidates/{c.id}/ack-sent",
                    json={"action_type": "request_pdf", "delivered": True})
    assert r.status_code == 409
    err = r.json()["detail"]
    assert err["error"] == "state_drift"
    assert err["client_action_type"] == "request_pdf"


# ══════════════════════════════════════════════════════════════════════════════
# ATTACK B4: force-complete candidate with no slots
# ══════════════════════════════════════════════════════════════════════════════
def test_B4_force_complete_no_slots(client, db_session):
    """force-complete a candidate that has zero slot rows."""
    from app.modules.im_intake.candidate_model import IntakeCandidate
    c = IntakeCandidate(user_id=1, boss_id="no_slots_boss", name="NS",
                        intake_status="collecting", source="plugin")
    db_session.add(c); db_session.commit()

    r = client.post(f"/api/intake/candidates/{c.id}/force-complete")
    print(f"[B4] force-complete no slots → {r.status_code}: {r.text[:200]}")
    assert r.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# ATTACK B5: collect-chat where the job_id on candidate points to deleted job
# ══════════════════════════════════════════════════════════════════════════════
def test_B5_collect_chat_with_deleted_job(client, db_session):
    """Candidate.job_id pointing to non-existent Job: FK enforced, then deleted.

    Insert candidate with valid job, then delete the job to simulate stale FK.
    """
    from app.modules.im_intake.candidate_model import IntakeCandidate
    from app.modules.screening.models import Job

    job = Job(user_id=1, title="temp", jd_text="x")
    db_session.add(job); db_session.commit()
    c = IntakeCandidate(user_id=1, boss_id="bad_job_boss", name="BJ",
                        intake_status="collecting", source="plugin",
                        job_id=job.id)
    db_session.add(c); db_session.commit()
    db_session.delete(job); db_session.commit()

    r = collect(client, boss_id="bad_job_boss")
    # Router: job = db.query(Job).filter_by(id=c.job_id).first() → None,
    # decide_next_action(job=None) handles gracefully.
    assert r.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# ATTACK B6: outbox ack on non-existent outbox_id
# ══════════════════════════════════════════════════════════════════════════════
def test_B6_outbox_ack_nonexistent(client):
    """POST /outbox/99999/ack — outbox_id doesn't exist."""
    r = client.post("/api/intake/outbox/99999/ack", json={"success": True})
    assert r.status_code == 404, f"Expected 404, got {r.status_code}"


def test_B6b_outbox_ack_wrong_user(client, db_session):
    """User 1 tries to ack a row that belongs to user 2.
    router checks: db.query(IntakeOutbox).filter_by(id=outbox_id, user_id=user_id)
    → 404 if user_id doesn't match."""
    from app.modules.im_intake.candidate_model import IntakeCandidate
    from app.modules.im_intake.outbox_model import IntakeOutbox
    c = IntakeCandidate(user_id=2, boss_id="u2outbox2", name="U",
                        intake_status="collecting", source="plugin")
    db_session.add(c); db_session.commit()
    row = IntakeOutbox(candidate_id=c.id, user_id=2, action_type="send_hard",
                       text="Q", slot_keys=[], status="claimed",
                       scheduled_for=datetime.now(timezone.utc))
    db_session.add(row); db_session.commit()

    r = client.post(f"/api/intake/outbox/{row.id}/ack", json={"success": True})
    assert r.status_code == 404, f"Cross-user outbox ack allowed: {r.status_code}"


# ══════════════════════════════════════════════════════════════════════════════
# ATTACK B7: reap_stale_claims with all claimed rows belonging to terminal candidates
# ══════════════════════════════════════════════════════════════════════════════
def test_B7_reap_stale_terminal_owner(db_session):
    """reap_stale_claims: rows whose owner is terminal should be expired, not re-pending."""
    from app.modules.im_intake.candidate_model import IntakeCandidate
    from app.modules.im_intake.outbox_model import IntakeOutbox
    from app.modules.im_intake.outbox_service import reap_stale_claims
    c = IntakeCandidate(user_id=1, boss_id="terminal_reap", name="TR",
                        intake_status="complete", source="plugin")
    db_session.add(c); db_session.commit()
    stale_time = datetime.now(timezone.utc) - timedelta(hours=2)
    row = IntakeOutbox(candidate_id=c.id, user_id=1, action_type="send_hard",
                       text="Q", slot_keys=[], status="claimed",
                       scheduled_for=stale_time, claimed_at=stale_time)
    db_session.add(row); db_session.commit()

    reaped = reap_stale_claims(db_session, stale_minutes=1)
    db_session.expire_all()
    db_session.refresh(row)
    assert row.status == "expired", f"Terminal owner: expected expired, got {row.status}"
    assert reaped == 1


# ══════════════════════════════════════════════════════════════════════════════
# ATTACK B8: cleanup_expired with candidates that have no expires_at
# ══════════════════════════════════════════════════════════════════════════════
def test_B8_cleanup_no_expires_at(db_session):
    """cleanup_expired: candidates with expires_at=None should NOT be abandoned."""
    from app.modules.im_intake.candidate_model import IntakeCandidate
    from app.modules.im_intake.outbox_service import cleanup_expired
    c = IntakeCandidate(user_id=1, boss_id="no_expires", name="NE",
                        intake_status="collecting", source="plugin",
                        expires_at=None)
    db_session.add(c); db_session.commit()

    result = cleanup_expired(db_session)
    db_session.expire_all()
    db_session.refresh(c)
    assert c.intake_status == "collecting", f"Should not abandon no-expires_at: {c.intake_status}"


# ══════════════════════════════════════════════════════════════════════════════
# ATTACK B9: is_running with complete_count exactly equal to target_count (boundary)
# ══════════════════════════════════════════════════════════════════════════════
def test_B9_is_running_at_exact_target(client, db_session):
    """is_running should return False when complete_count == target_count (not >=)."""
    from app.modules.im_intake.candidate_model import IntakeCandidate
    from app.modules.im_intake.settings_service import is_running, update as settings_update
    # Create exactly 3 complete candidates
    for i in range(3):
        c = IntakeCandidate(user_id=1, boss_id=f"done_{i}", name=f"D{i}",
                            intake_status="complete", source="plugin")
        db_session.add(c)
    db_session.commit()

    settings_update(db_session, user_id=1, enabled=True, target_count=3)
    # complete_count=3, target_count=3 → is_running should be False
    result = is_running(db_session, 1)
    assert not result, f"is_running should be False at boundary complete=target, got {result}"


# ══════════════════════════════════════════════════════════════════════════════
# ATTACK B10: concurrent collect-chat calls for same boss_id (race condition)
# ══════════════════════════════════════════════════════════════════════════════
def test_B10_concurrent_same_boss_id(client, db_session):
    """Two sequential collect-chat calls for the same boss_id.
    Due to the unique index on (user_id, boss_id), second call should be idempotent.
    But if two threads hit simultaneously (TOCTOU), could get IntegrityError."""
    from app.modules.im_intake.candidate_model import IntakeCandidate

    r1 = collect(client, boss_id="race_boss")
    r2 = collect(client, boss_id="race_boss")
    assert r1.status_code == 200
    assert r2.status_code == 200
    # Both should return same candidate_id
    assert r1.json()["candidate_id"] == r2.json()["candidate_id"], \
        f"Different candidate_ids! {r1.json()['candidate_id']} vs {r2.json()['candidate_id']}"


# ══════════════════════════════════════════════════════════════════════════════
# ATTACK B11: outbox ack_failed when row is already "sent" (not "claimed")
# ══════════════════════════════════════════════════════════════════════════════
def test_B11_ack_failed_on_sent_row(db_session):
    """ack_failed on a row that's already "sent" — should be a noop."""
    from app.modules.im_intake.candidate_model import IntakeCandidate
    from app.modules.im_intake.outbox_model import IntakeOutbox
    from app.modules.im_intake.outbox_service import ack_failed
    c = IntakeCandidate(user_id=1, boss_id="ack_fail_boss", name="AF",
                        intake_status="awaiting_reply", source="plugin")
    db_session.add(c); db_session.commit()
    row = IntakeOutbox(candidate_id=c.id, user_id=1, action_type="send_hard",
                       text="Q", slot_keys=[], status="sent",
                       scheduled_for=datetime.now(timezone.utc))
    db_session.add(row); db_session.commit()

    result = ack_failed(db_session, row.id, error="retry please")
    db_session.expire_all()
    db_session.refresh(row)
    assert row.status == "sent", f"ack_failed on sent row should be noop, got {row.status}"


# ══════════════════════════════════════════════════════════════════════════════
# ATTACK B12: DELETE candidate also deletes all slots (cascade check)
# ══════════════════════════════════════════════════════════════════════════════
def test_B12_delete_candidate_cascades_slots(client, db_session):
    """DELETE /candidates/{id} should cascade-delete all slots."""
    from app.modules.im_intake.candidate_model import IntakeCandidate
    from app.modules.im_intake.models import IntakeSlot
    from app.modules.im_intake.templates import HARD_SLOT_KEYS
    c = IntakeCandidate(user_id=1, boss_id="delete_boss", name="Del",
                        intake_status="collecting", source="plugin")
    db_session.add(c); db_session.commit()
    for k in HARD_SLOT_KEYS:
        db_session.add(IntakeSlot(candidate_id=c.id, slot_key=k, slot_category="hard"))
    db_session.commit()
    cid = c.id

    r = client.delete(f"/api/intake/candidates/{cid}")
    assert r.status_code == 204
    db_session.expire_all()
    remaining = db_session.query(IntakeSlot).filter_by(candidate_id=cid).count()
    assert remaining == 0, f"Slots not cascade-deleted: {remaining} remaining"


# ══════════════════════════════════════════════════════════════════════════════
# ATTACK B13: settings update with both enabled=None and target_count=None (noop)
# ══════════════════════════════════════════════════════════════════════════════
def test_B13_settings_update_all_none(client):
    """PUT settings with {enabled: null, target_count: null} — should be a noop."""
    client.put("/api/intake/settings", json={"enabled": True, "target_count": 5})
    r = client.put("/api/intake/settings", json={"enabled": None, "target_count": None})
    assert r.status_code == 200
    data = r.json()
    # Settings should remain enabled=True, target_count=5
    assert data["enabled"] == True
    assert data["target_count"] == 5


# ══════════════════════════════════════════════════════════════════════════════
# ATTACK B14: collect-chat with boss_id that contains unicode surrogates
# ══════════════════════════════════════════════════════════════════════════════
def test_B14_unicode_boss_id(client):
    """boss_id with various unicode: emoji, CJK, surrogates."""
    for boss_id in ["老板🔥123", "ボス_テスト", "老板_null_zero"]:
        r = collect(client, boss_id=boss_id)
        print(f"[B14] unicode boss_id={boss_id!r} → {r.status_code}")


# ══════════════════════════════════════════════════════════════════════════════
# ATTACK B15: mark-timed-out on already terminal candidate
# ══════════════════════════════════════════════════════════════════════════════
def test_B15_mark_timed_out_already_complete(client, db_session):
    """POST /mark-timed-out on complete candidate — should noop."""
    from app.modules.im_intake.candidate_model import IntakeCandidate
    c = IntakeCandidate(user_id=1, boss_id="timeout_done", name="TD",
                        intake_status="complete", source="plugin")
    db_session.add(c); db_session.commit()
    r = client.post(f"/api/intake/candidates/{c.id}/mark-timed-out")
    data = r.json()
    assert r.status_code == 200
    assert data.get("noop") == True, f"Expected noop=True, got {data}"


# ══════════════════════════════════════════════════════════════════════════════
# ATTACK B16: outbox claim with no pending rows
# ══════════════════════════════════════════════════════════════════════════════
def test_B16_claim_empty_outbox(client):
    """POST /outbox/claim when no pending rows — should return empty list."""
    enable(client)
    r = client.post("/api/intake/outbox/claim", json={"limit": 1})
    assert r.status_code == 200
    assert r.json()["items"] == []


# ══════════════════════════════════════════════════════════════════════════════
# ATTACK B17: generate_for_candidate with SEND_ACTIONS but candidate terminal
# ══════════════════════════════════════════════════════════════════════════════
def test_B17_generate_for_terminal_candidate(db_session):
    """generate_for_candidate on terminal candidate → must return None."""
    from app.modules.im_intake.candidate_model import IntakeCandidate
    from app.modules.im_intake.outbox_service import generate_for_candidate
    from app.modules.im_intake.decision import NextAction
    c = IntakeCandidate(user_id=1, boss_id="term_gen", name="TG",
                        intake_status="complete", source="plugin")
    db_session.add(c); db_session.commit()

    result = generate_for_candidate(db_session, c, NextAction(type="send_hard", text="Q"))
    assert result is None, f"Expected None for terminal candidate, got {result}"


# ══════════════════════════════════════════════════════════════════════════════
# ATTACK B18: autoscan rank with limit=0 (below ge=1)
# ══════════════════════════════════════════════════════════════════════════════
def test_B18_autoscan_rank_limit_zero(client):
    """GET /autoscan/rank?limit=0 — below ge=1, should be 422."""
    r = client.get("/api/intake/autoscan/rank?limit=0")
    assert r.status_code == 422, f"Expected 422, got {r.status_code}"


# ══════════════════════════════════════════════════════════════════════════════
# ATTACK B19: slot PUT on slot owned by another user's candidate
# ══════════════════════════════════════════════════════════════════════════════
def test_B19_slot_put_wrong_user(client, db_session):
    """PUT /slots/{id} for a slot whose candidate belongs to user 2 → 404."""
    from app.modules.im_intake.candidate_model import IntakeCandidate
    from app.modules.im_intake.models import IntakeSlot
    c = IntakeCandidate(user_id=2, boss_id="u2slot", name="U2S",
                        intake_status="collecting", source="plugin")
    db_session.add(c); db_session.commit()
    s = IntakeSlot(candidate_id=c.id, slot_key="arrival_date", slot_category="hard")
    db_session.add(s); db_session.commit()

    r = client.put(f"/api/intake/slots/{s.id}", json={"value": "Monday"})
    assert r.status_code == 404, f"Cross-user slot PUT: {r.status_code}: {r.text}"


# ══════════════════════════════════════════════════════════════════════════════
# ATTACK B20: slot PUT on terminal candidate (complete/abandoned = read-only)
# ══════════════════════════════════════════════════════════════════════════════
def test_B20_slot_put_on_complete_candidate(client, db_session):
    """PUT /slots/{id} for a slot whose candidate is complete → 409 Conflict."""
    from app.modules.im_intake.candidate_model import IntakeCandidate
    from app.modules.im_intake.models import IntakeSlot
    c = IntakeCandidate(user_id=1, boss_id="complete_slot", name="CS",
                        intake_status="complete", source="plugin")
    db_session.add(c); db_session.commit()
    s = IntakeSlot(candidate_id=c.id, slot_key="arrival_date", slot_category="hard")
    db_session.add(s); db_session.commit()

    r = client.put(f"/api/intake/slots/{s.id}", json={"value": "Monday"})
    assert r.status_code == 409, f"Expected 409 for complete candidate slot, got {r.status_code}"


# ══════════════════════════════════════════════════════════════════════════════
# ATTACK B21: collect-chat with message sent_at in the future
# ══════════════════════════════════════════════════════════════════════════════
def test_B21_future_message_timestamp(client):
    """Messages with sent_at far in the future — slot timestamp logic could be wrong."""
    future = (datetime.now(timezone.utc) + timedelta(days=365)).isoformat()
    msgs = [{"sender_id": "future_boss", "content": "到岗时间是明天", "sent_at": future}]
    r = collect(client, boss_id="future_boss", messages=msgs)
    assert r.status_code == 200
    print(f"[B21] future timestamp message → {r.json()['next_action']['type']}")


# ══════════════════════════════════════════════════════════════════════════════
# ATTACK B22: settings_service.update with target_count=-1 (validates in service)
# ══════════════════════════════════════════════════════════════════════════════
def test_B22_settings_service_negative_target(db_session):
    """settings_service.update with target_count=-1 raises ValueError."""
    from app.modules.im_intake.settings_service import update
    with pytest.raises(ValueError, match="target_count must be >= 0"):
        update(db_session, user_id=1, target_count=-1)


# ══════════════════════════════════════════════════════════════════════════════
# ATTACK B23: collect-chat messages with template injection in content
# ══════════════════════════════════════════════════════════════════════════════
def test_B23_template_injection_in_message(client):
    """Messages with {keyword} that could break str.format() in SlotFiller.
    BUG-035 already identified this — verify the safe_conversation escaping works."""
    msgs = [{"sender_id": "inject_boss",
             "content": "我{arrival_date}能来上班，{free_slots}都可以，{intern_duration}没问题"}]
    r = collect(client, boss_id="inject_boss", messages=msgs)
    assert r.status_code == 200
    print(f"[B23] template injection → {r.json()['next_action']['type']}")


# ══════════════════════════════════════════════════════════════════════════════
# ATTACK B24: abandon endpoint called twice (idempotency)
# ══════════════════════════════════════════════════════════════════════════════
def test_B24_double_abandon(client, db_session):
    """POST /candidates/{id}/abandon twice — should be idempotent."""
    from app.modules.im_intake.candidate_model import IntakeCandidate
    c = IntakeCandidate(user_id=1, boss_id="double_abandon", name="DA",
                        intake_status="collecting", source="plugin")
    db_session.add(c); db_session.commit()

    r1 = client.post(f"/api/intake/candidates/{c.id}/abandon")
    r2 = client.post(f"/api/intake/candidates/{c.id}/abandon")
    assert r1.status_code == 200
    assert r2.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# ATTACK B25: job_matcher with empty jobs list
# ══════════════════════════════════════════════════════════════════════════════
def test_B25_job_matcher_empty_jobs():
    """match_job_title with empty jobs list — should return None."""
    from app.modules.im_intake.job_matcher import match_job_title
    result = match_job_title("后端工程师", [])
    assert result is None


# ══════════════════════════════════════════════════════════════════════════════
# ATTACK B26: collect-chat with name="" (empty name)
# ══════════════════════════════════════════════════════════════════════════════
def test_B26_empty_name_candidate(client):
    """collect-chat with name='' — ensure_candidate stores empty name."""
    r = collect(client, boss_id="no_name_boss", name="")
    assert r.status_code == 200
    cid = r.json()["candidate_id"]
    r2 = client.get(f"/api/intake/candidates/{cid}")
    print(f"[B26] empty name candidate: {r2.json()['name']!r}")


# ══════════════════════════════════════════════════════════════════════════════
# ATTACK B27: cleanup_expired does NOT set audit log — silent abandonment
# ══════════════════════════════════════════════════════════════════════════════
def test_B27_cleanup_expired_no_audit(db_session):
    """cleanup_expired silently abandons candidates without audit log.
    If expires_at < now, status → abandoned without any F4_abandoned audit event."""
    from app.modules.im_intake.candidate_model import IntakeCandidate
    from app.modules.im_intake.outbox_service import cleanup_expired
    from app.core.audit.models import AuditEvent
    past = datetime.now(timezone.utc) - timedelta(days=20)
    c = IntakeCandidate(user_id=1, boss_id="expired_boss", name="E",
                        intake_status="collecting", source="plugin",
                        expires_at=past)
    db_session.add(c); db_session.commit()
    cid = c.id

    cleanup_expired(db_session)
    db_session.expire_all()
    db_session.refresh(c)
    assert c.intake_status == "abandoned"

    # Check if any audit event was created
    audit_count = (db_session.query(AuditEvent)
                   .filter_by(entity_type="intake_candidate", entity_id=cid)
                   .count())
    print(f"[B27] audit events after cleanup_expired abandon: {audit_count}")
    # BUG if audit_count == 0: silently abandoned with no trace
