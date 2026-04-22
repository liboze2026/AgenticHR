from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.resume.models import Resume


def promote_to_resume(db: Session, candidate: IntakeCandidate) -> Resume:
    if candidate.promoted_resume_id:
        existing = db.query(Resume).filter_by(id=candidate.promoted_resume_id).first()
        if existing:
            return existing

    r = Resume(
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
    return r
