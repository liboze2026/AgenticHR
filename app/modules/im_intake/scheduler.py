"""F4 常驻调度器：每 N 秒扫一次 intake，生成发件箱 + 清理过期。

设计决策：
- 独立 daemon 线程（模式与 app/modules/resume/_ai_parse_worker.py 一致）
- 每轮创建新 Session；失败吞掉日志，不停线程
- scan_once 是纯函数（接收 db），便于单测
"""
import logging
import threading
import time

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.im_intake.models import IntakeSlot
from app.modules.im_intake.decision import decide_next_action
from app.modules.im_intake.outbox_service import generate_for_candidate, cleanup_expired
from app.modules.screening.models import Job
from app.config import settings

logger = logging.getLogger(__name__)

_state = {"running": False, "thread": None}


def scan_once(db: Session) -> dict:
    """扫一次 active intake，生成 outbox；运行一次过期清理。返回统计。"""
    generated = 0
    seen = 0
    hard_max = getattr(settings, "f4_hard_max_asks", 3)
    pdf_to = getattr(settings, "f4_pdf_timeout_hours", 72)
    cooldown = getattr(settings, "f4_ask_cooldown_hours", 6)

    candidates = (db.query(IntakeCandidate)
                  .filter(IntakeCandidate.intake_status.in_(("collecting", "awaiting_reply")))
                  .all())
    for c in candidates:
        seen += 1
        slots = db.query(IntakeSlot).filter_by(candidate_id=c.id).all()
        job = db.query(Job).filter_by(id=c.job_id).first() if c.job_id else None
        action = decide_next_action(c, slots, job,
                                    hard_max=hard_max,
                                    pdf_timeout_h=pdf_to,
                                    ask_cooldown_h=cooldown)
        if generate_for_candidate(db, c, action) is not None:
            generated += 1

    cleanup = cleanup_expired(db)
    return {"seen": seen, "generated": generated, **cleanup}


def _loop(interval_sec: int):
    logger.info("F4 scheduler started, interval=%ss", interval_sec)
    while _state["running"]:
        try:
            db = SessionLocal()
            try:
                stats = scan_once(db)
                logger.info("F4 scan: %s", stats)
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
    if _state["running"]:
        return
    interval = int(interval_sec if interval_sec is not None
                   else getattr(settings, "f4_scheduler_interval_sec", 300))
    _state["running"] = True
    t = threading.Thread(target=_loop, args=(interval,), daemon=True, name="f4-scheduler")
    _state["thread"] = t
    t.start()


def stop() -> None:
    _state["running"] = False
