from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.resume.models import Resume


def promote_to_resume(db: Session, candidate: IntakeCandidate, user_id: int = 0) -> Resume:
    # Local import to break a circular dependency: outbox_service imports
    # IntakeService → service.py imports promote.py.
    from app.modules.im_intake.outbox_service import expire_pending_for_candidate

    if candidate.promoted_resume_id:
        existing = db.query(Resume).filter_by(id=candidate.promoted_resume_id).first()
        if existing:
            # Idempotent re-promote: still flush any zombie outbox so a stale
            # row from before the original promotion cannot fire later.
            expire_pending_for_candidate(db, candidate.id, reason="promote_idempotent")
            return existing

    # Merge semantics: if a Resume already exists with the same boss_id (e.g. from
    # F3 greet flow), update it in-place instead of creating a duplicate row.
    existing_by_boss = None
    if candidate.boss_id:
        q = db.query(Resume).filter(Resume.boss_id == candidate.boss_id)
        q = q.filter(Resume.user_id == user_id)
        existing_by_boss = q.first()

    if existing_by_boss is not None:
        r = existing_by_boss
        # Only fill fields that are empty on the existing row so we don't clobber
        # richer F3-sourced data; always upgrade intake_status to complete.
        if not r.name and candidate.name:
            r.name = candidate.name
        if not r.job_id and candidate.job_id:
            r.job_id = candidate.job_id
        if not r.pdf_path and candidate.pdf_path:
            r.pdf_path = candidate.pdf_path
        if not r.raw_text and candidate.raw_text:
            r.raw_text = candidate.raw_text
        r.intake_status = "complete"
        if not r.intake_started_at and candidate.intake_started_at:
            r.intake_started_at = candidate.intake_started_at
        r.intake_completed_at = datetime.now(timezone.utc)
        db.flush()

        candidate.promoted_resume_id = r.id
        candidate.intake_status = "complete"
        candidate.intake_completed_at = datetime.now(timezone.utc)
        # Expire any pending/claimed outbox so a stale scheduler row can't
        # fire after the candidate is already promoted.
        expire_pending_for_candidate(db, candidate.id, reason="promote_merge")
        return r

    r = Resume(
        user_id=user_id,
        name=candidate.name,
        boss_id=candidate.boss_id,
        job_id=candidate.job_id,
        pdf_path=candidate.pdf_path,
        raw_text=candidate.raw_text,
        status="passed",
        source="boss_zhipin",
        intake_status="complete",
        intake_started_at=candidate.intake_started_at,
        intake_completed_at=datetime.now(timezone.utc),
    )
    db.add(r)
    db.flush()

    candidate.promoted_resume_id = r.id
    candidate.intake_status = "complete"
    candidate.intake_completed_at = datetime.now(timezone.utc)
    expire_pending_for_candidate(db, candidate.id, reason="promote_new")
    return r
