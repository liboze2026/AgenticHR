"""统一的级联删除 helper.

Resume 表被多个外表 FK / 软引用：
- Interview.resume_id (FK, no ondelete) — 必须先清，否则 SQLite FK fail
- NotificationLog.interview_id (软引用，无 FK) — 跟随 Interview 一起清，避免孤儿
- MatchingResult.resume_id (软引用，无 FK) — 同上

之前 ResumeService.delete 只清 MatchingResult，导致单条 DELETE /api/resumes/{id}
在存在 Interview 时挂 IntegrityError 500（参见 /clear-all 已经做的逻辑）。
"""
from __future__ import annotations

from sqlalchemy.orm import Session


def purge_resumes_with_deps(db: Session, resume_ids: list[int]) -> dict:
    """级联清 resume_ids 自身 + 其 Interview / NotificationLog / MatchingResult.

    调用方在外层负责 commit；此 helper 只发 DELETE，不 commit，
    便于和 candidate/slot/outbox 的清理放在同一事务里。
    """
    if not resume_ids:
        return {"resumes": 0, "interviews": 0, "notifications": 0, "matching": 0}

    from app.modules.resume.models import Resume
    from app.modules.scheduling.models import Interview
    from app.modules.notification.models import NotificationLog

    interview_ids = [
        i for (i,) in db.query(Interview.id)
        .filter(Interview.resume_id.in_(resume_ids)).all()
    ]
    nlog_count = 0
    if interview_ids:
        nlog_count = db.query(NotificationLog).filter(
            NotificationLog.interview_id.in_(interview_ids)
        ).delete(synchronize_session=False)
    iv_count = db.query(Interview).filter(
        Interview.resume_id.in_(resume_ids)
    ).delete(synchronize_session=False)

    mr_count = 0
    try:
        from app.modules.matching.models import MatchingResult
        mr_count = db.query(MatchingResult).filter(
            MatchingResult.resume_id.in_(resume_ids)
        ).delete(synchronize_session=False)
    except Exception:
        pass

    r_count = db.query(Resume).filter(
        Resume.id.in_(resume_ids)
    ).delete(synchronize_session=False)

    return {
        "resumes": r_count,
        "interviews": iv_count,
        "notifications": nlog_count,
        "matching": mr_count,
    }


def purge_interviews_with_deps(db: Session, interview_ids: list[int]) -> dict:
    """级联清 interview_ids + 其 NotificationLog 软引用孤儿."""
    if not interview_ids:
        return {"interviews": 0, "notifications": 0}

    from app.modules.scheduling.models import Interview
    from app.modules.notification.models import NotificationLog

    nlog_count = db.query(NotificationLog).filter(
        NotificationLog.interview_id.in_(interview_ids)
    ).delete(synchronize_session=False)
    iv_count = db.query(Interview).filter(
        Interview.id.in_(interview_ids)
    ).delete(synchronize_session=False)
    return {"interviews": iv_count, "notifications": nlog_count}
