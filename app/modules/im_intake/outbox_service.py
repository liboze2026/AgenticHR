"""F4 outbox: 一条发件箱 = 一条待扩展代为发送的 Boss 消息。

单一职责：生成 / 认领 / 回执 / 过期清理 / 回收僵尸 claim。
与现有 decision.py + service.py 解耦——只接受 NextAction，不决定状态机。
"""
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session

from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.im_intake.outbox_model import IntakeOutbox
from app.modules.im_intake.decision import NextAction
from app.modules.im_intake.service import IntakeService

SEND_ACTIONS = {"send_hard", "request_pdf", "send_soft"}
ACTIVE_CANDIDATE_STATES = ("collecting", "awaiting_reply")
LIVE_OUTBOX_STATES = ("pending", "claimed")
_MAX_ERROR_LEN = 2000  # cap last_error payload so rogue stack traces don't bloat rows


def generate_for_candidate(db: Session, candidate: IntakeCandidate,
                           action: NextAction) -> IntakeOutbox | None:
    """给候选人生成一条待发 outbox；若已有 pending/claimed 则返回 None（幂等）。"""
    if action.type not in SEND_ACTIONS:
        return None
    existing = (db.query(IntakeOutbox)
                .filter_by(candidate_id=candidate.id)
                .filter(IntakeOutbox.status.in_(LIVE_OUTBOX_STATES))
                .first())
    if existing is not None:
        return None
    row = IntakeOutbox(
        candidate_id=candidate.id,
        user_id=candidate.user_id,
        action_type=action.type,
        text=action.text or "",
        slot_keys=action.meta.get("slot_keys") or action.meta.get("questions") or [],
        status="pending",
        scheduled_for=datetime.now(timezone.utc),
    )
    db.add(row); db.commit(); db.refresh(row)
    return row


def claim_batch(db: Session, user_id: int, limit: int = 1) -> list[IntakeOutbox]:
    """原子认领 pending outbox（→ claimed），返回给扩展去发送。

    **Hardened:** even if caller passes limit>1, we clamp to 1. Reason:
    2026-04-24 saw 3 outbox rows dispatch concurrently to a single Boss chat
    input, chars interleaved. Client-side mutex fixed it; this is the
    backend depth-defense so a misbehaving client cannot regress.

    Increments ``attempts`` at claim time (not at ack), so ``ack_failed``
    just re-queues without touching the counter.
    """
    limit = max(1, min(1, int(limit)))  # hard clamp
    now = datetime.now(timezone.utc)
    rows = (db.query(IntakeOutbox)
            .filter_by(user_id=user_id, status="pending")
            .filter(IntakeOutbox.scheduled_for <= now)
            .order_by(IntakeOutbox.scheduled_for.asc(), IntakeOutbox.id.asc())
            .limit(limit)
            .all())
    for r in rows:
        r.status = "claimed"
        r.claimed_at = now
        r.attempts += 1
    db.commit()
    return rows


def ack_sent(db: Session, outbox_id: int) -> IntakeOutbox | None:
    """扩展汇报发送成功：flip row → sent；复用 IntakeService.record_asked 推进 slot+candidate 状态。

    Atomicity: flip row state BEFORE calling ``record_asked`` so the single
    commit inside ``record_asked`` covers both the outbox flip and the slot
    updates. If ``record_asked`` raises, the transaction rolls back and the row
    stays ``claimed`` for a retry — avoiding the double-commit window where a
    crash would leave the row ``claimed`` forever.
    """
    row = db.query(IntakeOutbox).filter_by(id=outbox_id).first()
    if row is None or row.status != "claimed":
        return row
    # Flip row state first so the subsequent record_asked commit covers both
    # atomically; if record_asked fails, transaction rolls back and row stays claimed.
    row.status = "sent"
    row.sent_at = datetime.now(timezone.utc)
    candidate = db.query(IntakeCandidate).filter_by(id=row.candidate_id).first()
    if candidate is None:
        # No candidate — still need to commit the row.status flip ourselves.
        db.commit()
        return row

    svc = IntakeService(db=db, user_id=candidate.user_id)
    action = NextAction(type=row.action_type, text=row.text or "",
                        meta={"slot_keys": row.slot_keys or []})
    svc.record_asked(candidate, action)  # commits both flip + slot updates
    return row


def ack_failed(db: Session, outbox_id: int, error: str = "") -> IntakeOutbox | None:
    """扩展汇报发送失败：行回 pending 等下轮重试；不推进状态机。"""
    row = db.query(IntakeOutbox).filter_by(id=outbox_id).first()
    if row is None:
        return None
    row.status = "pending"   # re-queue; attempts already +1 at claim
    row.last_error = error[:_MAX_ERROR_LEN] if error else None
    row.claimed_at = None
    db.commit()
    return row


def reap_stale_claims(db: Session, stale_minutes: int = 10,
                      now: datetime | None = None) -> int:
    """把 claimed_at < now - stale_minutes 的 claimed 行回滚为 pending 以便下轮重试。

    Why: 扩展崩溃/Chrome 被杀导致 claim 后没 ack，这行会永远锁死，候选人也因
    幂等保护永远不再生成新 outbox。需要定期回收。attempts 不再自增——它只在
    claim 时计数，回收只负责 re-queue。
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    cutoff = now - timedelta(minutes=stale_minutes)
    # SQLite 存储常丢 tzinfo，改成 naive 比较避免 mixed-type 报错
    cutoff_naive = cutoff.replace(tzinfo=None) if cutoff.tzinfo else cutoff
    rows = (db.query(IntakeOutbox)
            .filter(IntakeOutbox.status == "claimed")
            .filter(IntakeOutbox.claimed_at.isnot(None))
            .all())
    reaped = 0
    for r in rows:
        ca = r.claimed_at
        if ca is None:
            continue
        ca_cmp = ca if ca.tzinfo else ca.replace(tzinfo=timezone.utc)
        if ca_cmp < cutoff:
            r.status = "pending"
            r.claimed_at = None
            r.last_error = (r.last_error or "") + f"[reaped stale claim at {now.isoformat()}]"
            r.last_error = r.last_error[:_MAX_ERROR_LEN]
            reaped += 1
    if reaped:
        db.commit()
    return reaped


def cleanup_expired(db: Session, now: datetime | None = None) -> dict[str, int]:
    """标 expires_at < now 且仍在 collecting/awaiting_reply 的候选人为 abandoned；
    其 pending/claimed outbox → expired。返回 {'abandoned': n, 'expired_outbox': m}。
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    to_abandon = (db.query(IntakeCandidate)
                  .filter(IntakeCandidate.expires_at.isnot(None))
                  .filter(IntakeCandidate.expires_at < now)
                  .filter(IntakeCandidate.intake_status.in_(ACTIVE_CANDIDATE_STATES))
                  .all())
    abandoned_ids = [c.id for c in to_abandon]
    for c in to_abandon:
        c.intake_status = "abandoned"
        c.intake_completed_at = now
    expired_cnt = 0
    if abandoned_ids:
        expired_cnt = (db.query(IntakeOutbox)
                       .filter(IntakeOutbox.candidate_id.in_(abandoned_ids))
                       .filter(IntakeOutbox.status.in_(LIVE_OUTBOX_STATES))
                       .update({"status": "expired"}, synchronize_session=False))
    db.commit()
    return {"abandoned": len(abandoned_ids), "expired_outbox": expired_cnt}
