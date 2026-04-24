"""F5 settings service — HR-facing master switch + target gate.

The scheduler, autoscan, and outbox claim all consult `is_running(db, user_id)`
before doing work. Semantics:
- enabled=False → HR paused; everything gates off
- enabled=True AND target_count==0 → not yet configured; gates off (safer
  default than "run forever")
- enabled=True AND complete_count >= target_count → done; gates off
"""
from sqlalchemy.orm import Session

from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.im_intake.settings_model import IntakeUserSettings


def get_or_create(db: Session, user_id: int) -> IntakeUserSettings:
    s = db.query(IntakeUserSettings).filter_by(user_id=user_id).first()
    if s is None:
        s = IntakeUserSettings(user_id=user_id, enabled=False, target_count=0)
        db.add(s); db.commit(); db.refresh(s)
    return s


def update(db: Session, user_id: int, *,
           enabled: bool | None = None,
           target_count: int | None = None) -> IntakeUserSettings:
    s = get_or_create(db, user_id)
    if enabled is not None:
        s.enabled = bool(enabled)
    if target_count is not None:
        if target_count < 0:
            raise ValueError("target_count must be >= 0")
        s.target_count = int(target_count)
    db.commit(); db.refresh(s)
    return s


def complete_count(db: Session, user_id: int) -> int:
    return (db.query(IntakeCandidate)
            .filter_by(user_id=user_id, intake_status="complete")
            .count())


def is_running(db: Session, user_id: int) -> bool:
    s = get_or_create(db, user_id)
    if not s.enabled:
        return False
    if s.target_count <= 0:
        return False
    return complete_count(db, user_id) < s.target_count
