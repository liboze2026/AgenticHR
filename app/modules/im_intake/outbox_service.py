"""F4 outbox: 一条发件箱 = 一条待扩展代为发送的 Boss 消息。

单一职责：生成 / 认领 / 回执 / 过期清理 / 回收僵尸 claim。
与现有 decision.py + service.py 解耦——只接受 NextAction，不决定状态机。
"""
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session

from app.config import settings
from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.im_intake.outbox_model import IntakeOutbox
from app.modules.im_intake.decision import NextAction
from app.modules.im_intake.service import IntakeService

SEND_ACTIONS = {"send_hard", "request_pdf", "send_soft"}
ACTIVE_CANDIDATE_STATES = ("collecting", "awaiting_reply")
TERMINAL_CANDIDATE_STATES = ("complete", "abandoned", "pending_human", "timed_out")
LIVE_OUTBOX_STATES = ("pending", "claimed")
_MAX_ERROR_LEN = 2000  # cap last_error payload so rogue stack traces don't bloat rows


def _outbox_max_age_hours() -> int:
    """Configured stale-row cap; centralized so tests can monkeypatch settings."""
    return int(getattr(settings, "f4_outbox_max_age_hours", 24))


def _is_terminal(candidate: IntakeCandidate | None) -> bool:
    """True iff the candidate is in a state where no further outbox traffic
    should be generated, claimed, or acted upon. Defense-in-depth check used
    by every outbox lifecycle function — a single source of truth so a new
    terminal state added in the future automatically propagates."""
    return candidate is not None and candidate.intake_status in TERMINAL_CANDIDATE_STATES


def generate_for_candidate(db: Session, candidate: IntakeCandidate,
                           action: NextAction) -> IntakeOutbox | None:
    """给候选人生成一条待发 outbox；若已有 pending/claimed 则返回 None（幂等）。

    Terminal-state guard: a candidate that has already been promoted, abandoned,
    or marked pending_human must never receive a new outbox row — even if a
    stale scheduler tick or a router miscall asks for one. Returns ``None``
    silently so callers can blindly call without checking state.
    """
    if action.type not in SEND_ACTIONS:
        return None
    if _is_terminal(candidate):
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
    limit = 1  # hard-capped; caller's value is intentionally ignored
    now = datetime.now(timezone.utc)
    # Stale-row cap: any pending row scheduled more than max_age_hours ago is
    # auto-expired at claim time. Defends against the case where the scheduler
    # ticked while the extension was offline (laptop closed, weekend, etc.) —
    # without this, the row sits in pending for days and fires the moment the
    # extension reconnects, asking a question whose context is long gone.
    max_age_hours = _outbox_max_age_hours()
    age_cutoff = now - timedelta(hours=max_age_hours)
    # SQLite often loses tzinfo on stored datetimes — compare naive to be safe
    age_cutoff_cmp = age_cutoff.replace(tzinfo=None)

    # FIFO scan; skip & auto-expire any row whose owner became terminal
    # between scheduling and claim time (zombie outbox prevention).
    candidates = (db.query(IntakeOutbox)
                  .filter_by(user_id=user_id, status="pending")
                  .filter(IntakeOutbox.scheduled_for <= now)
                  .order_by(IntakeOutbox.scheduled_for.asc(),
                            IntakeOutbox.id.asc())
                  .all())
    rows: list[IntakeOutbox] = []
    expired_terminal = 0
    expired_stale = 0
    for r in candidates:
        sf = r.scheduled_for
        sf_cmp = sf if (sf and sf.tzinfo is None) else (sf.replace(tzinfo=None) if sf else None)
        if sf_cmp is not None and sf_cmp < age_cutoff_cmp:
            r.status = "expired"
            r.last_error = ((r.last_error or "")
                            + f"[claim: stale row >{max_age_hours}h, scheduler "
                              f"tick happened while ext offline]")[:_MAX_ERROR_LEN]
            expired_stale += 1
            continue
        owner = db.query(IntakeCandidate).filter_by(id=r.candidate_id).first()
        if _is_terminal(owner):
            r.status = "expired"
            r.last_error = ((r.last_error or "")
                            + "[claim: owner terminal]")[:_MAX_ERROR_LEN]
            expired_terminal += 1
            continue
        r.status = "claimed"
        r.claimed_at = now
        r.attempts += 1
        rows.append(r)
        if len(rows) >= limit:
            break
    if rows or expired_terminal or expired_stale:
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

    if _is_terminal(candidate):
        # Late ack on a terminal candidate (e.g. promoted 2 days ago, scheduler
        # row only just got dispatched). Mark the row sent for audit but DO NOT
        # call record_asked — it would regress intake_status and re-touch slots.
        row.last_error = ((row.last_error or "")
                          + "[ack: owner terminal, skip record_asked]")[:_MAX_ERROR_LEN]
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
            owner = db.query(IntakeCandidate).filter_by(id=r.candidate_id).first()
            if _is_terminal(owner):
                # Don't re-pending a row whose owner is terminal — that would
                # just re-trigger the same zombie cycle. Expire instead.
                r.status = "expired"
                r.claimed_at = None
                r.last_error = ((r.last_error or "")
                                + f"[reap: owner terminal at {now.isoformat()}]")[:_MAX_ERROR_LEN]
            else:
                r.status = "pending"
                r.claimed_at = None
                r.last_error = ((r.last_error or "")
                                + f"[reaped stale claim at {now.isoformat()}]")[:_MAX_ERROR_LEN]
            reaped += 1
    if reaped:
        db.commit()
    return reaped


def expire_pending_for_candidate(db: Session, candidate_id: int,
                                 reason: str = "superseded") -> int:
    """Mark all pending/claimed outbox rows for ``candidate_id`` as expired.

    Used by the inline-send path (router.ack_sent): when the extension's
    autoscan has already directly sent the message and acked, any leftover
    outbox row from a prior scheduler tick must be invalidated, otherwise
    outbox poll will dispatch the same question again 30s later.

    Returns the number of rows transitioned. Caller is responsible for
    committing — this function uses its own commit so callers may safely
    invoke after their own commit.
    """
    rows = (db.query(IntakeOutbox)
            .filter(IntakeOutbox.candidate_id == candidate_id)
            .filter(IntakeOutbox.status.in_(LIVE_OUTBOX_STATES))
            .all())
    if not rows:
        return 0
    tag = f"[expired: {reason}]"
    for r in rows:
        r.status = "expired"
        r.last_error = ((r.last_error or "") + tag)[:_MAX_ERROR_LEN]
    db.commit()
    return len(rows)


def cleanup_expired(db: Session, now: datetime | None = None) -> dict[str, int]:
    """标 expires_at < now 且仍在 collecting/awaiting_reply 的候选人为 abandoned；
    其 pending/claimed outbox → expired。同时清理超 ``f4_outbox_max_age_hours``
    的 stale pending/claimed 行 (即使 owner 仍非终态)。
    返回 {'abandoned': n, 'expired_outbox': m, 'expired_stale': k}。
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

    # Stale-row sweep: any live outbox row scheduled more than
    # ``f4_outbox_max_age_hours`` ago becomes expired regardless of owner state.
    max_age_hours = _outbox_max_age_hours()
    age_cutoff = now - timedelta(hours=max_age_hours)
    age_cutoff_cmp = age_cutoff.replace(tzinfo=None)
    stale_rows = (db.query(IntakeOutbox)
                  .filter(IntakeOutbox.status.in_(LIVE_OUTBOX_STATES))
                  .all())
    expired_stale = 0
    tag = f"[cleanup: stale row >{max_age_hours}h]"
    for r in stale_rows:
        sf = r.scheduled_for
        if sf is None:
            continue
        sf_cmp = sf if sf.tzinfo is None else sf.replace(tzinfo=None)
        if sf_cmp < age_cutoff_cmp:
            r.status = "expired"
            r.last_error = ((r.last_error or "") + tag)[:_MAX_ERROR_LEN]
            expired_stale += 1

    db.commit()
    return {"abandoned": len(abandoned_ids), "expired_outbox": expired_cnt,
            "expired_stale": expired_stale}
