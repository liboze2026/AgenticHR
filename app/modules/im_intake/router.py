"""F4 Boss IM Intake HTTP API."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.modules.auth.deps import get_current_user_id
from app.modules.im_intake.models import IntakeSlot
from app.modules.im_intake.schemas import (
    CandidateDetailOut,
    CandidateOut,
    SchedulerStatus,
    SlotOut,
    SlotPatchIn,
)
from app.modules.im_intake.templates import HARD_SLOT_KEYS
from app.modules.resume.models import Resume
from app.modules.screening.models import Job

router = APIRouter(prefix="/api/intake", tags=["intake"])


def _scheduler():
    """Late import to avoid circular import with app.main."""
    from app import main as _main
    return getattr(_main, "intake_scheduler", None)


def _candidate_summary(r: Resume, slots: list[IntakeSlot], job_title: str = "") -> CandidateOut:
    expected = list(HARD_SLOT_KEYS) + ["pdf"]
    soft_keys = [s.slot_key for s in slots if s.slot_category == "soft"]
    expected += soft_keys
    done = sum(1 for s in slots if s.value)
    last = max((s.updated_at for s in slots if getattr(s, "updated_at", None)), default=r.intake_started_at)
    return CandidateOut(
        resume_id=r.id,
        boss_id=r.boss_id,
        name=r.name,
        job_id=getattr(r, "job_id", None),
        job_title=job_title,
        intake_status=r.intake_status,
        progress_done=done,
        progress_total=len(expected),
        last_activity_at=last,
    )


@router.get("/candidates")
def list_candidates(
    status: str | None = None,
    job_id: int | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    q = db.query(Resume).filter(Resume.boss_id != "")
    if status:
        q = q.filter(Resume.intake_status == status)
    if job_id:
        q = q.filter(Resume.job_id == job_id)
    total = q.count()
    rows = q.order_by(Resume.updated_at.desc()).offset((page - 1) * size).limit(size).all()
    items = []
    for r in rows:
        slots = db.query(IntakeSlot).filter_by(resume_id=r.id).all()
        job = db.query(Job).filter_by(id=r.job_id).first() if getattr(r, "job_id", None) else None
        items.append(_candidate_summary(r, slots, job.title if job else ""))
    return {"items": items, "total": total, "page": page, "size": size}


@router.get("/candidates/{resume_id}", response_model=CandidateDetailOut)
def get_candidate(
    resume_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    r = db.query(Resume).filter_by(id=resume_id).first()
    if not r:
        raise HTTPException(404, "not found")
    slots = db.query(IntakeSlot).filter_by(resume_id=r.id).all()
    job = db.query(Job).filter_by(id=r.job_id).first() if getattr(r, "job_id", None) else None
    summary = _candidate_summary(r, slots, job.title if job else "")
    return CandidateDetailOut(
        **summary.model_dump(),
        slots=[SlotOut.model_validate(s, from_attributes=True) for s in slots],
    )


@router.put("/slots/{slot_id}", response_model=SlotOut)
def patch_slot(
    slot_id: int,
    body: SlotPatchIn,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    s = db.query(IntakeSlot).filter_by(id=slot_id).first()
    if not s:
        raise HTTPException(404, "slot not found")
    s.value = body.value
    s.source = "manual"
    s.answered_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(s)
    return SlotOut.model_validate(s, from_attributes=True)


@router.post("/candidates/{resume_id}/abandon")
def abandon(
    resume_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    r = db.query(Resume).filter_by(id=resume_id).first()
    if not r:
        raise HTTPException(404, "not found")
    r.intake_status = "abandoned"
    db.commit()
    return {"ok": True}


@router.post("/candidates/{resume_id}/force-complete")
def force_complete(
    resume_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    r = db.query(Resume).filter_by(id=resume_id).first()
    if not r:
        raise HTTPException(404, "not found")
    r.intake_status = "complete"
    r.intake_completed_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True}


@router.get("/scheduler/status", response_model=SchedulerStatus)
def scheduler_status(user_id: int = Depends(get_current_user_id)):
    sched = _scheduler()
    used = getattr(sched.adapter, "_operations_today", 0) if sched else 0
    return SchedulerStatus(
        running=sched.running if sched else False,
        next_run_at=sched.next_run_at if sched else None,
        daily_cap_used=used,
        daily_cap_max=settings.boss_max_operations_per_day,
        last_batch_size=sched.last_batch_size if sched else 0,
    )


@router.post("/scheduler/pause")
def scheduler_pause(user_id: int = Depends(get_current_user_id)):
    sched = _scheduler()
    if sched:
        sched.pause()
    return {"ok": True}


@router.post("/scheduler/resume")
def scheduler_resume(user_id: int = Depends(get_current_user_id)):
    sched = _scheduler()
    if sched:
        sched.resume()
    return {"ok": True}


@router.post("/scheduler/tick-now")
async def scheduler_tick(user_id: int = Depends(get_current_user_id)):
    sched = _scheduler()
    if sched:
        await sched.tick_now()
    return {"ok": True}
