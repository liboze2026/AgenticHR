"""TDD for B2: autoscan/rank must demote candidates whose chat snapshot is
non-empty but hard slots remain blank — these are extractor blind spots and
should not be re-picked ahead of fresh candidates.
"""
from datetime import datetime, timedelta, timezone

from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.im_intake.models import IntakeSlot
from app.modules.im_intake.settings_model import IntakeUserSettings as IntakeSettings
from app.modules.im_intake.templates import HARD_SLOT_KEYS


def _enable_autoscan(db_session):
    s = IntakeSettings(user_id=1, enabled=True, target_count=999)
    db_session.add(s)
    db_session.commit()


def _mk(db_session, name, boss_id, status="collecting", chat=None,
        slot_values=None, ask_counts=None, updated_at=None):
    slot_values = slot_values or {}
    ask_counts = ask_counts or {}
    c = IntakeCandidate(
        boss_id=boss_id, name=name, intake_status=status,
        source="plugin", chat_snapshot=chat, user_id=1,
    )
    if updated_at:
        c.updated_at = updated_at
    db_session.add(c)
    db_session.flush()
    for k in HARD_SLOT_KEYS:
        s = IntakeSlot(
            candidate_id=c.id, slot_key=k, slot_category="hard",
            value=slot_values.get(k, ""),
            ask_count=ask_counts.get(k, 0),
        )
        db_session.add(s)
    db_session.commit()
    return c


def test_blind_extract_candidate_demoted(client, db_session):
    """Candidate with chat snapshot but empty slots after asking is demoted
    behind a fresh candidate even when its updated_at is older.
    """
    _enable_autoscan(db_session)
    older = datetime.now(timezone.utc) - timedelta(days=2)
    blind = _mk(
        db_session, "陷入循环", "bxLoop",
        chat={"messages": [{"sender_id": "bxLoop", "content": "hi"},
                           {"sender_id": "bxLoop", "content": "hi2"}]},
        ask_counts={k: 1 for k in HARD_SLOT_KEYS},
        updated_at=older,
    )
    fresh = _mk(db_session, "新人", "bxFresh",
                updated_at=datetime.now(timezone.utc))

    r = client.get("/api/intake/autoscan/rank?limit=10")
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    ids = [it["candidate_id"] for it in items]
    assert blind.id in ids and fresh.id in ids
    assert ids.index(fresh.id) < ids.index(blind.id), (
        f"fresh ({fresh.id}) should be ranked before blind ({blind.id}); got {ids}"
    )


def test_no_chat_candidate_keeps_normal_priority(client, db_session):
    """Candidate without chat_snapshot uses standard updated_at ordering."""
    _enable_autoscan(db_session)
    older = datetime.now(timezone.utc) - timedelta(days=2)
    no_chat_old = _mk(db_session, "老候选", "bxOld",
                      chat=None, updated_at=older)
    no_chat_new = _mk(db_session, "新候选", "bxNew",
                      chat=None, updated_at=datetime.now(timezone.utc))

    r = client.get("/api/intake/autoscan/rank?limit=10")
    items = r.json()["items"]
    ids = [it["candidate_id"] for it in items]
    # older comes first under "oldest updated_at first" rule
    assert ids.index(no_chat_old.id) < ids.index(no_chat_new.id)


def test_filled_chat_candidate_keeps_normal_priority(client, db_session):
    """If slots are filled, chat_snapshot presence shouldn't demote."""
    _enable_autoscan(db_session)
    older = datetime.now(timezone.utc) - timedelta(days=2)
    filled = _mk(
        db_session, "已填齐", "bxFilled", status="awaiting_reply",
        chat={"messages": [{"sender_id": "bxFilled", "content": "yes"}]},
        slot_values={k: "value" for k in HARD_SLOT_KEYS},
        updated_at=older,
    )
    new = _mk(db_session, "新候选B", "bxNewB", status="collecting",
              updated_at=datetime.now(timezone.utc))

    r = client.get("/api/intake/autoscan/rank?limit=10")
    items = r.json()["items"]
    ids = [it["candidate_id"] for it in items]
    # collecting beats awaiting_reply in the existing first sort key,
    # so new(collecting) before filled(awaiting_reply) is expected
    assert ids.index(new.id) < ids.index(filled.id)
