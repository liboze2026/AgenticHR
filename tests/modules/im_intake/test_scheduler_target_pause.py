"""F5 scan_once must respect per-user is_running gate."""
from datetime import datetime, timezone, timedelta

from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.im_intake.models import IntakeSlot
from app.modules.im_intake.scheduler import scan_once
from app.modules.im_intake.settings_service import update as settings_update
from app.modules.im_intake.templates import HARD_SLOT_KEYS


def _mk_candidate_with_pending_slot(db, user_id: int, boss_id: str):
    now = datetime.now(timezone.utc)
    c = IntakeCandidate(
        user_id=user_id, boss_id=boss_id, name=boss_id,
        intake_status="collecting", source="plugin",
        intake_started_at=now, expires_at=now + timedelta(days=14),
    )
    db.add(c); db.flush()
    for k in HARD_SLOT_KEYS:
        db.add(IntakeSlot(candidate_id=c.id, slot_key=k, slot_category="hard"))
    db.add(IntakeSlot(candidate_id=c.id, slot_key="pdf", slot_category="pdf"))
    db.commit()
    return c


def test_scan_once_skips_user_with_settings_disabled(db_session):
    _mk_candidate_with_pending_slot(db_session, user_id=1, boss_id="boss-1")
    settings_update(db_session, user_id=1, enabled=False, target_count=10)
    stats = scan_once(db_session)
    assert stats["seen"] == 0
    assert stats["generated"] == 0


def test_scan_once_skips_user_who_reached_target(db_session):
    _mk_candidate_with_pending_slot(db_session, user_id=1, boss_id="boss-1")
    db_session.add_all([
        IntakeCandidate(user_id=1, boss_id="c1", intake_status="complete", source="plugin"),
        IntakeCandidate(user_id=1, boss_id="c2", intake_status="complete", source="plugin"),
    ])
    db_session.commit()
    settings_update(db_session, user_id=1, enabled=True, target_count=2)
    stats = scan_once(db_session)
    assert stats["seen"] == 0


def test_scan_once_runs_for_user_below_target(db_session):
    c = _mk_candidate_with_pending_slot(db_session, user_id=1, boss_id="boss-1")
    settings_update(db_session, user_id=1, enabled=True, target_count=10)
    stats = scan_once(db_session)
    assert stats["seen"] == 1
    assert stats["generated"] == 1


def test_scan_once_isolates_users(db_session):
    """User 1 paused, user 2 running: only user 2 is scanned."""
    _mk_candidate_with_pending_slot(db_session, user_id=1, boss_id="b-1")
    _mk_candidate_with_pending_slot(db_session, user_id=2, boss_id="b-2")
    settings_update(db_session, user_id=1, enabled=False, target_count=5)
    settings_update(db_session, user_id=2, enabled=True, target_count=5)
    stats = scan_once(db_session)
    assert stats["seen"] == 1
