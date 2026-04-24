"""F4 outbox: 一条发件箱 = 一条待扩展代为发送的 Boss 消息。

单一职责：生成 / 认领 / 回执 / 过期清理。
与现有 decision.py + service.py 解耦——只接受 NextAction，不决定状态机。
"""
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.im_intake.outbox_model import IntakeOutbox
from app.modules.im_intake.decision import NextAction

SEND_ACTIONS = {"send_hard", "request_pdf", "send_soft"}


def generate_for_candidate(db: Session, candidate: IntakeCandidate,
                           action: NextAction) -> IntakeOutbox | None:
    """给候选人生成一条待发 outbox；若已有 pending/claimed 则返回 None（幂等）。"""
    if action.type not in SEND_ACTIONS:
        return None
    existing = (db.query(IntakeOutbox)
                .filter_by(candidate_id=candidate.id)
                .filter(IntakeOutbox.status.in_(("pending", "claimed")))
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


def claim_batch(db: Session, user_id: int, limit: int = 5) -> list[IntakeOutbox]:
    """原子认领一批 pending outbox（→ claimed），返回给扩展去发送。

    Increments ``attempts`` at claim time (not at ack), so ``ack_failed`` in
    Task 5 just re-queues without touching the counter.
    """
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
