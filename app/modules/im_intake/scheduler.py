"""F4 常驻调度器：每 N 秒扫一次 intake，生成发件箱 + 清理过期。

设计决策：
- 独立 daemon 线程（模式与 app/modules/resume/_ai_parse_worker.py 一致）
- 每轮创建新 Session；失败吞掉日志，不停线程
- scan_once 是纯函数（接收 db），便于单测
- chat_snapshot 新鲜度门：扩展 autoscan 走"collect-chat 直发"内联路径，
  会更新 candidate.chat_snapshot.captured_at。若该时间 < freshness 窗口，
  scheduler 推断扩展正在主导该候选人，让出避免重复发送（与扩展内联 ack-sent
  竞争同一个 send_hard 决策会导致同问题被发两次：一次内联，一次 outbox 30s
  后被 poll 拿走）。
"""
import logging
import threading
import time
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.im_intake.models import IntakeSlot
from app.modules.im_intake.decision import decide_next_action
from app.modules.im_intake.outbox_service import (
    generate_for_candidate, cleanup_expired, reap_stale_claims,
    ACTIVE_CANDIDATE_STATES,
)
from app.modules.im_intake.settings_service import is_running as _settings_is_running
from app.modules.screening.models import Job
from app.config import settings

logger = logging.getLogger(__name__)

_state = {"running": False, "thread": None}
_lock = threading.Lock()


def _chat_snapshot_is_fresh(candidate: IntakeCandidate, freshness_sec: int) -> bool:
    """True if the candidate's chat_snapshot.captured_at is within the
    freshness window — the extension's autoscan path is actively driving
    this candidate, scheduler should defer to avoid duplicate sends.

    Returns False on missing/malformed snapshot so brand-new candidates
    fall through to scheduler emission (existing safety-net behavior)."""
    snap = getattr(candidate, "chat_snapshot", None) or {}
    captured_raw = snap.get("captured_at") if isinstance(snap, dict) else None
    if not captured_raw:
        return False
    try:
        captured = datetime.fromisoformat(str(captured_raw).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return False
    if captured.tzinfo is None:
        captured = captured.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - captured).total_seconds()
    return age <= freshness_sec


def scan_once(db: Session) -> dict[str, int]:
    """扫一次 active intake，生成 outbox；运行一次过期清理。返回统计。

    Per-user gate: for each distinct user_id with active candidates, skip the
    whole user if settings.is_running is False (paused OR target reached).
    Target/pause is the HR-facing master switch; cleanup + reap still run
    globally because they're corrections, not emissions.
    """
    generated = 0
    seen = 0
    deferred_fresh = 0
    hard_max = getattr(settings, "f4_hard_max_asks", 3)
    pdf_to = getattr(settings, "f4_pdf_timeout_hours", 72)
    cooldown = getattr(settings, "f4_ask_cooldown_hours", 6)
    # Default freshness window = 2 × scheduler interval, so a candidate the
    # extension covered in the last tick is left alone for one more cycle.
    interval = getattr(settings, "f4_scheduler_interval_sec", 300)
    freshness_sec = getattr(settings, "f4_chat_freshness_sec", interval * 2)

    active_user_ids = [row[0] for row in (
        db.query(IntakeCandidate.user_id)
        .filter(IntakeCandidate.intake_status.in_(ACTIVE_CANDIDATE_STATES))
        .distinct()
        .all()
    )]

    for uid in active_user_ids:
        if not _settings_is_running(db, uid):
            continue
        candidates = (db.query(IntakeCandidate)
                      .filter(IntakeCandidate.user_id == uid)
                      .filter(IntakeCandidate.intake_status.in_(ACTIVE_CANDIDATE_STATES))
                      .all())
        for c in candidates:
            seen += 1
            # TOCTOU guard: HR may hit "pause" or target may be reached mid-loop.
            # Re-check is cheap and prevents post-pause emissions.
            if not _settings_is_running(db, uid):
                break
            if _chat_snapshot_is_fresh(c, freshness_sec):
                deferred_fresh += 1
                continue
            slots = db.query(IntakeSlot).filter_by(candidate_id=c.id).all()
            job = db.query(Job).filter_by(id=c.job_id).first() if c.job_id else None
            action = decide_next_action(c, slots, job,
                                        hard_max=hard_max,
                                        pdf_timeout_h=pdf_to,
                                        ask_cooldown_h=cooldown)
            if generate_for_candidate(db, c, action) is not None:
                generated += 1

    stale_min = getattr(settings, "f4_claim_stale_minutes", 10)
    reaped = reap_stale_claims(db, stale_minutes=stale_min)
    cleanup = cleanup_expired(db)
    return {"seen": seen, "generated": generated,
            "deferred_fresh": deferred_fresh,
            "reaped": reaped, **cleanup}


def _loop(interval_sec: int):
    logger.info("F4 scheduler started, interval=%ss", interval_sec)
    while _state["running"]:
        try:
            db = SessionLocal()
            try:
                stats = scan_once(db)
                if any(stats.get(k, 0) for k in ("generated", "abandoned", "expired_outbox", "reaped")):
                    logger.info("F4 scan: %s", stats)
                else:
                    logger.debug("F4 scan idle: %s", stats)
            finally:
                db.close()
        except Exception as e:
            logger.exception("F4 scheduler scan failed: %s", e)
        for _ in range(interval_sec):
            if not _state["running"]:
                break
            time.sleep(1)
    logger.info("F4 scheduler stopped")


def start(interval_sec: int | None = None) -> None:
    with _lock:
        if _state["running"] and _state["thread"] is not None and _state["thread"].is_alive():
            return
        interval = int(interval_sec if interval_sec is not None
                       else getattr(settings, "f4_scheduler_interval_sec", 300))
        _state["running"] = True
        t = threading.Thread(target=_loop, args=(interval,), daemon=True, name="f4-scheduler")
        _state["thread"] = t
        t.start()


def stop(timeout: float = 5.0) -> None:
    with _lock:
        _state["running"] = False
        t = _state["thread"]
        _state["thread"] = None
    if t is not None and t.is_alive():
        t.join(timeout=timeout)
