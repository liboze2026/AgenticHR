"""F4 Boss IM Intake HTTP API (extension-driven; no backend Playwright daemon)."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.config import settings
from app.core.audit.logger import log_event
from app.database import get_db
from app.modules.auth.deps import get_current_user_id
from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.im_intake.models import IntakeSlot
from app.modules.im_intake.outbox_model import IntakeOutbox
from app.modules.im_intake.outbox_service import (
    ack_failed as _outbox_ack_failed,
    ack_sent as _outbox_ack_sent,
    claim_batch as _outbox_claim_batch,
)
from app.modules.im_intake.settings_service import (
    get_or_create as _settings_get_or_create,
    update as _settings_update,
    complete_count as _settings_complete_count,
    is_running as _settings_is_running,
)
from app.modules.im_intake.schemas import (
    AckSentIn,
    CandidateDetailOut,
    CandidateOut,
    CollectChatIn,
    CollectChatOut,
    IntakeSettingsIn,
    IntakeSettingsOut,
    NextActionOut,
    OutboxAckIn,
    OutboxClaimIn,
    OutboxClaimItem,
    OutboxClaimOut,
    SlotOut,
    SlotPatchIn,
    StartConversationOut,
)
from app.modules.im_intake.promote import promote_to_resume
from app.modules.im_intake.service import IntakeService
from app.modules.im_intake.templates import HARD_SLOT_KEYS
from app.core.audit.models import AuditEvent
from app.modules.screening.models import Job

router = APIRouter(prefix="/api/intake", tags=["intake"])

import logging as _logging
_log = _logging.getLogger(__name__)


def _audit_safe(f_stage: str, action: str, entity_id: int, payload: dict | None = None,
                reviewer_id: int | None = None) -> None:
    try:
        log_event(
            f_stage=f_stage, action=action, entity_type="intake_candidate",
            entity_id=entity_id, input_payload=payload, reviewer_id=reviewer_id,
        )
    except Exception as e:
        _log.warning("audit log_event %s failed: %s", f_stage, e)


def _build_service(db: Session, user_id: int = 0) -> IntakeService:
    """Late import to avoid circular import with app.main."""
    from app import main as _main
    return IntakeService(
        db=db,
        llm=getattr(_main, "llm_client", None),
        hard_max_asks=getattr(settings, "f4_hard_max_asks", 3),
        pdf_timeout_hours=getattr(settings, "f4_pdf_timeout_hours", 72),
        ask_cooldown_hours=getattr(settings, "f4_ask_cooldown_hours", 6),
        soft_max_n=getattr(settings, "f4_soft_question_max", 3),
        user_id=user_id,
    )


def _candidate_summary(c: IntakeCandidate, slots: list[IntakeSlot], job_title: str = "") -> CandidateOut:
    expected = list(HARD_SLOT_KEYS) + ["pdf"]
    soft_keys = [s.slot_key for s in slots if s.slot_category == "soft"]
    expected += soft_keys
    done = sum(1 for s in slots if s.value)
    last = max((s.updated_at for s in slots if getattr(s, "updated_at", None)), default=c.intake_started_at)
    return CandidateOut(
        resume_id=c.id,  # NOTE: field kept as resume_id for frontend compat; semantically = candidate_id
        boss_id=c.boss_id,
        name=c.name,
        job_id=getattr(c, "job_id", None),
        job_title=job_title,
        intake_status=c.intake_status,
        progress_done=done,
        progress_total=len(expected),
        last_activity_at=last,
        promoted_resume_id=getattr(c, "promoted_resume_id", None),
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
    q = db.query(IntakeCandidate).filter(IntakeCandidate.user_id == user_id)
    if status:
        q = q.filter(IntakeCandidate.intake_status == status)
    if job_id:
        q = q.filter(IntakeCandidate.job_id == job_id)
    total = q.count()
    rows = q.order_by(IntakeCandidate.updated_at.desc()).offset((page - 1) * size).limit(size).all()
    items = []
    for c in rows:
        slots = db.query(IntakeSlot).filter_by(candidate_id=c.id).all()
        job = db.query(Job).filter_by(id=c.job_id).first() if getattr(c, "job_id", None) else None
        items.append(_candidate_summary(c, slots, job.title if job else ""))
    return {"items": items, "total": total, "page": page, "size": size}


@router.get("/candidates/{candidate_id}", response_model=CandidateDetailOut)
def get_candidate(
    candidate_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    c = db.query(IntakeCandidate).filter_by(id=candidate_id, user_id=user_id).first()
    if not c:
        raise HTTPException(404, "not found")
    slots = db.query(IntakeSlot).filter_by(candidate_id=c.id).all()
    job = db.query(Job).filter_by(id=c.job_id).first() if getattr(c, "job_id", None) else None
    summary = _candidate_summary(c, slots, job.title if job else "")
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
    # Verify the parent candidate belongs to the calling user
    parent = db.query(IntakeCandidate).filter_by(id=s.candidate_id, user_id=user_id).first()
    if not parent:
        raise HTTPException(404, "slot not found")
    s.value = body.value
    s.source = "manual"
    s.answered_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(s)
    return SlotOut.model_validate(s, from_attributes=True)


@router.post("/candidates/{candidate_id}/abandon")
def abandon(
    candidate_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    c = db.query(IntakeCandidate).filter_by(id=candidate_id, user_id=user_id).first()
    if not c:
        raise HTTPException(404, "not found")
    c.intake_status = "abandoned"
    db.commit()
    _audit_safe("f4_abandoned", "manual_abandon", c.id, {"boss_id": c.boss_id}, reviewer_id=user_id)
    return {"ok": True}


@router.delete("/candidates/{candidate_id}", status_code=204)
def delete_candidate(
    candidate_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    c = db.query(IntakeCandidate).filter_by(id=candidate_id, user_id=user_id).first()
    if not c:
        raise HTTPException(404, "not found")
    db.query(IntakeSlot).filter_by(candidate_id=c.id).delete(synchronize_session=False)
    db.delete(c)
    db.commit()


@router.post("/candidates/{candidate_id}/force-complete")
def force_complete(
    candidate_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    c = db.query(IntakeCandidate).filter_by(id=candidate_id, user_id=user_id).first()
    if not c:
        raise HTTPException(404, "not found")
    resume = promote_to_resume(db, c, user_id=user_id)
    db.commit()
    _audit_safe(
        "f4_completed", "manual_complete", c.id,
        {"boss_id": c.boss_id, "promoted_resume_id": resume.id if resume else None},
        reviewer_id=user_id,
    )
    return {"ok": True, "promoted_resume_id": resume.id if resume else None}


@router.post("/collect-chat", response_model=CollectChatOut)
async def collect_chat(
    body: CollectChatIn,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    svc = _build_service(db, user_id=user_id)
    c = svc.ensure_candidate(body.boss_id, name=body.name, job_intention=body.job_intention)
    job = db.query(Job).filter_by(id=c.job_id).first() if c.job_id else None

    messages = [m.model_dump() for m in body.messages]

    if body.pdf_present and body.pdf_url and not c.pdf_path:
        slots = svc.ensure_slot_rows(c.id)
        slots["pdf"].value = body.pdf_url
        slots["pdf"].source = "plugin_detected"
        slots["pdf"].answered_at = datetime.now(timezone.utc)
        c.pdf_path = body.pdf_url
        db.commit()
        _audit_safe("f4_pdf_received", "pdf_uploaded", c.id,
                    {"pdf_url": body.pdf_url}, reviewer_id=user_id)

    action = await svc.analyze_chat(c, messages, job)
    svc.apply_terminal(c, action, user_id=user_id)
    db.refresh(c)
    return CollectChatOut(
        candidate_id=c.id,
        intake_status=c.intake_status,
        next_action=NextActionOut(
            type=action.type,
            text=action.text,
            slot_keys=action.meta.get("slot_keys", []),
        ),
    )


@router.post("/candidates/{candidate_id}/ack-sent")
async def ack_sent(
    candidate_id: int,
    body: AckSentIn,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    if not body.delivered:
        return {"ok": True, "noop": True}
    c = db.query(IntakeCandidate).filter_by(id=candidate_id, user_id=user_id).first()
    if not c:
        raise HTTPException(404, "candidate not found")
    svc = _build_service(db, user_id=user_id)
    job = db.query(Job).filter_by(id=c.job_id).first() if c.job_id else None
    action = await svc.analyze_chat(c, messages=[], job=job)
    if action.type != body.action_type:
        raise HTTPException(409, f"state mismatch: expected {action.type}, got {body.action_type}")
    svc.record_asked(c, action)
    return {"ok": True}


@router.get("/daily-cap")
def get_daily_cap(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """Today's new-candidate usage vs. configured daily cap."""
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    used = (
        db.query(func.count(IntakeCandidate.id))
        .filter(IntakeCandidate.user_id == user_id)
        .filter(IntakeCandidate.created_at >= today_start)
        .scalar() or 0
    )
    cap = getattr(settings, "f4_daily_cap", 200)
    return {"date": today_start.date().isoformat(), "used": int(used), "cap": int(cap),
            "remaining": max(0, int(cap) - int(used))}


# ---- F5 Task 6: settings HTTP API ----

def _settings_response(db: Session, user_id: int) -> IntakeSettingsOut:
    s = _settings_get_or_create(db, user_id)
    return IntakeSettingsOut(
        enabled=s.enabled,
        target_count=s.target_count,
        complete_count=_settings_complete_count(db, user_id),
        is_running=_settings_is_running(db, user_id),
    )


@router.get("/settings", response_model=IntakeSettingsOut)
def get_intake_settings(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    return _settings_response(db, user_id)


@router.put("/settings", response_model=IntakeSettingsOut)
def put_intake_settings(
    body: IntakeSettingsIn,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    _settings_update(db, user_id,
                     enabled=body.enabled,
                     target_count=body.target_count)
    return _settings_response(db, user_id)


@router.get("/autoscan/rank")
def autoscan_rank(
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """Rank candidates most in need of an autoscan tick.

    Strategy: collecting first then awaiting_reply, oldest updated_at first.
    """
    if not _settings_is_running(db, user_id):
        return {"items": [], "limit": limit}
    rows = (
        db.query(IntakeCandidate)
        .filter(IntakeCandidate.user_id == user_id)
        .filter(IntakeCandidate.intake_status.in_(["collecting", "awaiting_reply"]))
        .order_by(
            # collecting (0) before awaiting_reply (1)
            case((IntakeCandidate.intake_status == "collecting", 0), else_=1),
            IntakeCandidate.updated_at.asc(),
        )
        .limit(limit)
        .all()
    )
    items = [
        {"candidate_id": c.id, "boss_id": c.boss_id, "name": c.name,
         "intake_status": c.intake_status,
         "last_activity_at": c.updated_at.isoformat() if c.updated_at else None}
        for c in rows
    ]
    return {"items": items, "limit": limit}


@router.post("/autoscan/tick")
def autoscan_tick(
    body: dict = Body(default_factory=dict),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """Plugin reports tick results; backend writes F4_autoscan_tick audit + returns day stats."""
    processed = int(body.get("processed", 0))
    skipped = int(body.get("skipped", 0))
    total_seen = int(body.get("total", 0))
    _audit_safe(
        "f4_autoscan_tick", "tick", 0,
        {"processed": processed, "skipped": skipped, "total_seen": total_seen,
         "ts": body.get("ts")},
        reviewer_id=user_id,
    )
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    tick_count = (
        db.query(func.count(AuditEvent.event_id))
        .filter(AuditEvent.f_stage == "f4_autoscan_tick")
        .filter(AuditEvent.reviewer_id == user_id)
        .filter(AuditEvent.created_at >= today_start)
        .scalar() or 0
    )
    return {"ok": True, "ticks_today": int(tick_count),
            "processed": processed, "skipped": skipped, "total_seen": total_seen}


@router.post("/candidates/{candidate_id}/start-conversation", response_model=StartConversationOut)
def start_conversation(
    candidate_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    c = db.query(IntakeCandidate).filter_by(id=candidate_id, user_id=user_id).first()
    if not c:
        raise HTTPException(404, "candidate not found")
    base = settings.boss_chat_url_template.format(boss_id=c.boss_id)
    sep = "&" if "?" in base else "?"
    deep_link = f"{base}{sep}intake_candidate_id={c.id}"
    return StartConversationOut(candidate_id=c.id, boss_id=c.boss_id, deep_link=deep_link)


# ---- F4 Task 9: outbox HTTP API ----

@router.post("/outbox/claim", response_model=OutboxClaimOut)
def outbox_claim(
    body: OutboxClaimIn,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    if not _settings_is_running(db, user_id):
        return OutboxClaimOut(items=[])
    rows = _outbox_claim_batch(db, user_id=user_id, limit=body.limit)
    cand_ids = {r.candidate_id for r in rows}
    boss_by_cand: dict[int, str] = {}
    if cand_ids:
        boss_by_cand = dict(
            db.query(IntakeCandidate.id, IntakeCandidate.boss_id)
            .filter(IntakeCandidate.id.in_(cand_ids)).all()
        )
    return OutboxClaimOut(items=[
        OutboxClaimItem(
            id=r.id, candidate_id=r.candidate_id,
            boss_id=boss_by_cand.get(r.candidate_id, ""),
            action_type=r.action_type,
            text=r.text or "", slot_keys=r.slot_keys or [], attempts=r.attempts,
        ) for r in rows
    ])


@router.post("/outbox/{outbox_id}/ack")
def outbox_ack(
    outbox_id: int,
    body: OutboxAckIn,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    row = db.query(IntakeOutbox).filter_by(id=outbox_id, user_id=user_id).first()
    if row is None:
        raise HTTPException(404, "outbox not found")
    if body.success:
        _outbox_ack_sent(db, outbox_id)
    else:
        _outbox_ack_failed(db, outbox_id, error=body.error)
    return {"ok": True}
