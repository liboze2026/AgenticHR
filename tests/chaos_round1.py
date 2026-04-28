"""chaos-qa-hunter Round 1: boundary + auth + input validation attacks."""
import pytest
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient


# ── helpers ──────────────────────────────────────────────────────────────────

def collect(client, boss_id="b1", messages=None, skip_outbox=True, **kw):
    body = {"boss_id": boss_id, "messages": messages or [], "skip_outbox": skip_outbox}
    body.update(kw)
    return client.post("/api/intake/collect-chat", json=body)


def enable_running(client, target=10):
    client.put("/api/intake/settings", json={"enabled": True, "target_count": target})


# ══════════════════════════════════════════════════════════════════════════════
# ATTACK 1: boss_id = spaces only → min_length=1 passes but semantically empty
# ══════════════════════════════════════════════════════════════════════════════
def test_A1_spaces_only_boss_id(client):
    """boss_id='   ' passes Pydantic min_length=1 but should reject."""
    r = collect(client, boss_id="   ")
    # Spaces-only boss_id creates a row with boss_id='   '
    # Two calls with '   ' for same user → unique constraint hit = 500 or 200?
    r2 = collect(client, boss_id="   ")
    assert r.status_code == 200
    assert r2.status_code == 200  # idempotent
    # BUG: whitespace-only boss_id accepted, creates garbage row
    data = r.json()
    assert "candidate_id" in data


# ══════════════════════════════════════════════════════════════════════════════
# ATTACK 2: boss_id SQL injection
# ══════════════════════════════════════════════════════════════════════════════
def test_A2_sql_injection_boss_id(client):
    """SQL injection in boss_id — ORM should parameterize safely."""
    evil = "'; DROP TABLE intake_candidates; --"
    r = collect(client, boss_id=evil)
    assert r.status_code == 200
    # Table should still exist
    r2 = collect(client, boss_id="normal_after_injection")
    assert r2.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# ATTACK 3: 10000 messages (over the 500 limit)
# ══════════════════════════════════════════════════════════════════════════════
def test_A3_ten_thousand_messages(client):
    """10000 messages should be truncated to 500 by f4_max_chat_messages."""
    msgs = [{"sender_id": "b999", "content": "x" * 50} for _ in range(10000)]
    r = collect(client, boss_id="b999", messages=msgs)
    assert r.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# ATTACK 4: single message with 100KB content
# ══════════════════════════════════════════════════════════════════════════════
def test_A4_single_giant_message(client):
    """Single message with 100KB content."""
    msgs = [{"sender_id": "giant_boss", "content": "X" * 100_000}]
    r = collect(client, boss_id="giant_boss", messages=msgs)
    assert r.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# ATTACK 5: messages with missing/null fields
# ══════════════════════════════════════════════════════════════════════════════
def test_A5_messages_null_sender_id(client):
    """Messages with null sender_id — should not crash LLM path."""
    msgs = [{"sender_id": None, "content": "hello"}]
    r = collect(client, boss_id="null_sender")
    assert r.status_code == 200


def test_A5b_messages_null_content(client):
    """Messages with null content."""
    msgs = [{"sender_id": "b1", "content": None}]
    # ChatMessageIn.content is str, not Optional[str] — should fail validation
    r = client.post("/api/intake/collect-chat",
                    json={"boss_id": "null_content", "messages": msgs})
    # What happens?
    print(f"[A5b] null content msg → {r.status_code}: {r.text[:200]}")


def test_A5c_messages_missing_content(client):
    """Messages with missing content key entirely."""
    msgs = [{"sender_id": "b1"}]  # content missing
    r = client.post("/api/intake/collect-chat",
                    json={"boss_id": "no_content_key", "messages": msgs})
    print(f"[A5c] missing content key → {r.status_code}: {r.text[:200]}")


# ══════════════════════════════════════════════════════════════════════════════
# ATTACK 6: pdf_url path traversal
# ══════════════════════════════════════════════════════════════════════════════
def test_A6_pdf_url_path_traversal(client):
    """pdf_url with path traversal stored unvalidated in DB."""
    r = collect(client, boss_id="pdf_path_boss",
                pdf_present=True, pdf_url="../../../etc/passwd")
    assert r.status_code == 200
    # Check it was stored in DB
    r2 = client.get("/api/intake/candidates")
    candidates = r2.json()["items"]
    # path traversal URL is stored without validation → security issue
    print(f"[A6] pdf_url stored: look for ../../../etc/passwd in DB")


# ══════════════════════════════════════════════════════════════════════════════
# ATTACK 7: ack-sent on nonexistent candidate
# ══════════════════════════════════════════════════════════════════════════════
def test_A7_ack_sent_nonexistent(client):
    """ack-sent for candidate_id that doesn't exist."""
    r = client.post("/api/intake/candidates/99999/ack-sent",
                    json={"action_type": "send_hard", "delivered": True})
    assert r.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# ATTACK 8: ack-sent on already-terminal candidate
# ══════════════════════════════════════════════════════════════════════════════
def test_A8_ack_sent_on_terminal_candidate(client, db_session):
    """ack-sent on a candidate that's already 'complete'."""
    from app.modules.im_intake.candidate_model import IntakeCandidate
    c = IntakeCandidate(user_id=1, boss_id="terminal_b", name="T",
                        intake_status="complete", source="plugin")
    db_session.add(c); db_session.commit()

    r = client.post(f"/api/intake/candidates/{c.id}/ack-sent",
                    json={"action_type": "send_hard", "delivered": True})
    # Should succeed (record_asked guards against terminal regression)
    assert r.status_code == 200
    db_session.expire_all()
    db_session.refresh(c)
    # Status must stay "complete", not regress to "awaiting_reply"
    assert c.intake_status == "complete", f"REGRESSION: status became {c.intake_status}"


# ══════════════════════════════════════════════════════════════════════════════
# ATTACK 9: autoscan/tick with non-numeric processed field
# ══════════════════════════════════════════════════════════════════════════════
def test_A9_autoscan_tick_non_numeric(client):
    """autoscan/tick with string 'processed' — int() will throw."""
    r = client.post("/api/intake/autoscan/tick",
                    json={"processed": "evil_string", "skipped": 0, "total": 0})
    # int("evil_string") should raise ValueError → 500 or 422?
    print(f"[A9] non-numeric processed → {r.status_code}: {r.text[:200]}")
    # BUG if 500


def test_A9b_autoscan_tick_injection_ts(client):
    """autoscan/tick with injection payload in 'ts' field."""
    r = client.post("/api/intake/autoscan/tick",
                    json={"processed": 1, "ts": "<script>alert(1)</script>"})
    assert r.status_code == 200  # stored in audit but shouldn't execute


# ══════════════════════════════════════════════════════════════════════════════
# ATTACK 10: settings target_count boundary
# ══════════════════════════════════════════════════════════════════════════════
def test_A10_settings_target_zero_with_enabled(client):
    """enabled=True but target_count=0 → is_running should be False."""
    client.put("/api/intake/settings", json={"enabled": True, "target_count": 0})
    r = client.get("/api/intake/settings")
    data = r.json()
    assert not data["is_running"], f"is_running should be False when target=0, got: {data}"


def test_A10b_settings_target_negative(client):
    """target_count=-1 should be rejected (ge=0 in schema)."""
    r = client.put("/api/intake/settings", json={"enabled": True, "target_count": -1})
    # Should be 422
    assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text[:200]}"


def test_A10c_settings_extremely_large_target(client):
    """target_count=2**31-1 (INT_MAX) — should store without error."""
    r = client.put("/api/intake/settings", json={"enabled": True, "target_count": 2**31 - 1})
    assert r.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# ATTACK 11: user isolation — user 1 tries to access user 2's candidate
# ══════════════════════════════════════════════════════════════════════════════
def test_A11_user_isolation(client, db_session):
    """User 1 (default client) tries to read/modify user 2's candidate."""
    from app.modules.im_intake.candidate_model import IntakeCandidate
    c = IntakeCandidate(user_id=2, boss_id="u2_boss", name="U2Candidate",
                        intake_status="collecting", source="plugin")
    db_session.add(c); db_session.commit()

    # ack-sent should 404 because user_id=1 can't see user_id=2's candidate
    r = client.post(f"/api/intake/candidates/{c.id}/ack-sent",
                    json={"action_type": "send_hard", "delivered": True})
    assert r.status_code == 404, f"User isolation FAIL: {r.status_code}"

    # candidate detail should also 404
    r2 = client.get(f"/api/intake/candidates/{c.id}")
    assert r2.status_code == 404, f"User isolation detail FAIL: {r2.status_code}"


# ══════════════════════════════════════════════════════════════════════════════
# ATTACK 12: status PATCH with invalid state
# ══════════════════════════════════════════════════════════════════════════════
def test_A12_status_patch_invalid_state(client, db_session):
    """PATCH /candidates/{id}/status with invalid status value."""
    from app.modules.im_intake.candidate_model import IntakeCandidate
    c = IntakeCandidate(user_id=1, boss_id="patch_boss", name="P",
                        intake_status="collecting", source="plugin")
    db_session.add(c); db_session.commit()

    r = client.patch(f"/api/intake/candidates/{c.id}/status",
                     json={"status": "INVALID_STATUS"})
    assert r.status_code == 400, f"Expected 400, got {r.status_code}: {r.text[:200]}"


def test_A12b_status_patch_empty_string(client, db_session):
    """PATCH /candidates/{id}/status with empty string."""
    from app.modules.im_intake.candidate_model import IntakeCandidate
    c = IntakeCandidate(user_id=1, boss_id="patch_boss2", name="P2",
                        intake_status="collecting", source="plugin")
    db_session.add(c); db_session.commit()

    r = client.patch(f"/api/intake/candidates/{c.id}/status", json={"status": ""})
    assert r.status_code == 400, f"Expected 400, got {r.status_code}: {r.text[:200]}"


# ══════════════════════════════════════════════════════════════════════════════
# ATTACK 13: slot PATCH with empty value (min_length=1)
# ══════════════════════════════════════════════════════════════════════════════
def test_A13_slot_patch_empty_value(client, db_session):
    """PATCH slot with empty value — should be blocked by min_length=1."""
    from app.modules.im_intake.candidate_model import IntakeCandidate
    from app.modules.im_intake.models import IntakeSlot
    c = IntakeCandidate(user_id=1, boss_id="slot_boss", name="S",
                        intake_status="collecting", source="plugin")
    db_session.add(c); db_session.commit()
    s = IntakeSlot(candidate_id=c.id, slot_key="arrival_date", slot_category="hard")
    db_session.add(s); db_session.commit()

    r = client.patch(f"/api/intake/slots/{s.id}", json={"value": ""})
    assert r.status_code == 422, f"Expected 422 for empty value, got {r.status_code}"


# ══════════════════════════════════════════════════════════════════════════════
# ATTACK 14: start-conversation deep-link injection via boss_id
# ══════════════════════════════════════════════════════════════════════════════
def test_A14_start_conversation_boss_id_injection(client, db_session):
    """boss_id with URL injection chars stored in deep_link."""
    from app.modules.im_intake.candidate_model import IntakeCandidate
    evil_boss = "evil&redirect=https://attacker.com"
    c = IntakeCandidate(user_id=1, boss_id=evil_boss, name="Evil",
                        intake_status="collecting", source="plugin")
    db_session.add(c); db_session.commit()

    r = client.post(f"/api/intake/candidates/{c.id}/start-conversation")
    data = r.json()
    link = data.get("deep_link", "")
    print(f"[A14] deep_link with injection boss_id: {link}")
    # Attacker can inject extra URL params into deep_link
    # This is a stored URL injection bug


# ══════════════════════════════════════════════════════════════════════════════
# ATTACK 15: outbox ack on wrong user's outbox row
# ══════════════════════════════════════════════════════════════════════════════
def test_A15_outbox_ack_cross_user(client, db_session):
    """User 1 tries to ack user 2's outbox row."""
    from app.modules.im_intake.candidate_model import IntakeCandidate
    from app.modules.im_intake.outbox_model import IntakeOutbox
    c = IntakeCandidate(user_id=2, boss_id="u2_outbox", name="U2O",
                        intake_status="collecting", source="plugin")
    db_session.add(c); db_session.commit()
    row = IntakeOutbox(candidate_id=c.id, user_id=2, action_type="send_hard",
                       text="Q", slot_keys=["arrival_date"], status="claimed",
                       scheduled_for=datetime.now(timezone.utc))
    db_session.add(row); db_session.commit()

    # User 1 (default client) tries to ack user 2's row
    r = client.post(f"/api/intake/outbox/{row.id}/ack",
                    json={"success": True})
    assert r.status_code == 404, f"Cross-user outbox ack FAIL: {r.status_code}"


# ══════════════════════════════════════════════════════════════════════════════
# ATTACK 16: collect-chat with job_intention containing injection chars
# ══════════════════════════════════════════════════════════════════════════════
def test_A16_job_intention_xss(client):
    """job_intention with XSS payload — stored and returned without sanitization?"""
    r = collect(client, boss_id="xss_boss",
                job_intention="<script>alert('xss')</script>")
    assert r.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# ATTACK 17: ack-sent called twice (double-ack)
# ══════════════════════════════════════════════════════════════════════════════
def test_A17_double_ack_sent(client, db_session):
    """Call ack-sent twice on the same candidate — should be idempotent."""
    from app.modules.im_intake.candidate_model import IntakeCandidate
    c = IntakeCandidate(user_id=1, boss_id="double_ack", name="DA",
                        intake_status="awaiting_reply", source="plugin")
    db_session.add(c); db_session.commit()

    r1 = client.post(f"/api/intake/candidates/{c.id}/ack-sent",
                     json={"action_type": "send_hard", "delivered": True})
    r2 = client.post(f"/api/intake/candidates/{c.id}/ack-sent",
                     json={"action_type": "send_hard", "delivered": True})
    assert r1.status_code == 200
    assert r2.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# ATTACK 18: job_matcher edge cases
# ══════════════════════════════════════════════════════════════════════════════
def test_A18_job_matcher_single_char():
    """match_job_title with single-char job title — bigram produces empty set."""
    from app.modules.im_intake.job_matcher import match_job_title, string_similarity
    # Single char: no bigrams → empty set
    result = string_similarity("a", "ab")
    print(f"[A18] similarity('a','ab') = {result}")
    # Both single char
    result2 = string_similarity("a", "a")
    print(f"[A18] similarity('a','a') = {result2}")
    # Empty strings
    result3 = string_similarity("", "")
    print(f"[A18] similarity('','') = {result3}")
    result4 = string_similarity("ab", "")
    print(f"[A18] similarity('ab','') = {result4}")


# ══════════════════════════════════════════════════════════════════════════════
# ATTACK 19: promote_to_resume with user_id=0 creates orphan
# ══════════════════════════════════════════════════════════════════════════════
def test_A19_promote_with_user_id_zero(db_session):
    """promote_to_resume with user_id=0 creates orphan Resume."""
    from app.modules.im_intake.candidate_model import IntakeCandidate
    from app.modules.im_intake.promote import promote_to_resume
    from app.modules.resume.models import Resume
    c = IntakeCandidate(user_id=1, boss_id="orphan_boss", name="Orphan",
                        intake_status="complete", source="plugin")
    db_session.add(c); db_session.commit()
    r = promote_to_resume(db_session, c, user_id=0)
    db_session.commit()
    # Resume created with user_id=0 → no real user owns it
    print(f"[A19] orphan resume user_id={r.user_id}, id={r.id}")
    assert r.user_id == 0, "Expected orphan with user_id=0"


# ══════════════════════════════════════════════════════════════════════════════
# ATTACK 20: daily-cap endpoint with no candidates today
# ══════════════════════════════════════════════════════════════════════════════
def test_A20_daily_cap_fresh_db(client):
    """daily-cap on fresh DB should return 0 used."""
    r = client.get("/api/intake/daily-cap")
    assert r.status_code == 200
    data = r.json()
    assert data["used"] == 0
    assert data["remaining"] == data["cap"]


# ══════════════════════════════════════════════════════════════════════════════
# ATTACK 21: force-complete already terminal candidate
# ══════════════════════════════════════════════════════════════════════════════
def test_A21_force_complete_already_complete(client, db_session):
    """force-complete a candidate already in 'complete' state — idempotent?"""
    from app.modules.im_intake.candidate_model import IntakeCandidate
    c = IntakeCandidate(user_id=1, boss_id="already_done", name="Done",
                        intake_status="complete", source="plugin")
    db_session.add(c); db_session.commit()
    r = client.post(f"/api/intake/candidates/{c.id}/force-complete")
    assert r.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# ATTACK 22: collect-chat boss_id = very long string (512+ chars)
# ══════════════════════════════════════════════════════════════════════════════
def test_A22_very_long_boss_id(client):
    """boss_id exceeding column size (64 chars defined in model)."""
    long_id = "B" * 200  # > Column(String(64))
    r = collect(client, boss_id=long_id)
    # SQLite silently truncates? Or stores full? Or error?
    print(f"[A22] 200-char boss_id → {r.status_code}: {r.text[:200]}")


# ══════════════════════════════════════════════════════════════════════════════
# ATTACK 23: PATCH status directly to "timed_out" (manual)
# ══════════════════════════════════════════════════════════════════════════════
def test_A23_patch_status_to_timed_out(client, db_session):
    """Can HR patch status to 'timed_out' via the general status endpoint?"""
    from app.modules.im_intake.candidate_model import IntakeCandidate
    c = IntakeCandidate(user_id=1, boss_id="timed_boss", name="T",
                        intake_status="collecting", source="plugin")
    db_session.add(c); db_session.commit()
    r = client.patch(f"/api/intake/candidates/{c.id}/status",
                     json={"status": "timed_out"})
    print(f"[A23] patch to timed_out → {r.status_code}: {r.text[:200]}")


# ══════════════════════════════════════════════════════════════════════════════
# ATTACK 24: abandon then collect-chat (zombie resurrection?)
# ══════════════════════════════════════════════════════════════════════════════
def test_A24_collect_chat_after_abandon(client, db_session):
    """Can collect-chat be called again after candidate is abandoned?"""
    from app.modules.im_intake.candidate_model import IntakeCandidate
    c = IntakeCandidate(user_id=1, boss_id="zombie_boss", name="Z",
                        intake_status="abandoned", source="plugin")
    db_session.add(c); db_session.commit()

    r = collect(client, boss_id="zombie_boss")
    data = r.json()
    print(f"[A24] collect-chat on abandoned candidate → {r.status_code}, action={data.get('next_action',{}).get('type')}")
    # Does analyze_chat respect terminal status? What action is returned?
    db_session.expire_all()
    db_session.refresh(c)
    print(f"[A24] status after: {c.intake_status}")


# ══════════════════════════════════════════════════════════════════════════════
# ATTACK 25: decision.py — all slots missing (no slot rows at all)
# ══════════════════════════════════════════════════════════════════════════════
def test_A25_decide_with_empty_slots():
    """decide_next_action with zero slot rows for HARD_SLOT_KEYS."""
    from app.modules.im_intake.decision import decide_next_action
    from app.modules.im_intake.candidate_model import IntakeCandidate

    c = IntakeCandidate(boss_id="bare", name="Bare", intake_status="collecting",
                        source="plugin", user_id=1)
    # slots list has none of the HARD_SLOT_KEYS
    action = decide_next_action(c, [], None)
    print(f"[A25] decide_next_action with no slots: {action.type}")
    # hard_unfilled = [k for k in HARD_SLOT_KEYS if k in by and ...] — "k in by" is False
    # so hard_unfilled = [] → pdf check → pdf not in by → pdf is None → hard_filled check
    # hard_filled = all(by[k].value for k in HARD_SLOT_KEYS if k in by)
    # → vacuous all() = True → goes to "complete"
    # BUG: no slots = complete instead of send_hard!
