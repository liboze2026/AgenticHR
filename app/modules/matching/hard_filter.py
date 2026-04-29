"""硬筛 → F2 串联的共享 helper.

抽出独立模块避免 router/triggers/service 之间循环 import。

硬筛规则 (与 list_matched_for_job 一致):
  - 四项齐全 (三 hard slot + PDF)
  - 学历 >= job.education_min
  - 院校等级 >= job.school_tier_min
"""
from __future__ import annotations
import logging

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def hard_filter_resume_ids(db: Session, user_id: int, job_id: int) -> set[int]:
    """硬筛通过的 candidate → 翻译为 Resume.id 集合 (按需 promote).

    翻译失败的 candidate 静默跳过, 不阻塞批量。
    """
    from app.modules.resume.intake_view_service import list_matched_for_job
    from app.modules.im_intake.candidate_model import IntakeCandidate
    from app.modules.resume.models import Resume

    matched_dicts = list_matched_for_job(db, user_id=user_id, job_id=job_id)
    cand_ids = [d["id"] for d in matched_dicts]
    if not cand_ids:
        return set()

    resume_ids: set[int] = set()
    for cid in cand_ids:
        cand = db.query(IntakeCandidate).filter_by(id=cid, user_id=user_id).first()
        if not cand:
            continue
        if cand.promoted_resume_id:
            existing = db.query(Resume).filter_by(id=cand.promoted_resume_id).first()
            if existing and existing.user_id == user_id:
                resume_ids.add(existing.id)
                continue
        try:
            from app.modules.im_intake.promote import promote_to_resume
            r = promote_to_resume(db, cand, user_id=user_id)
            db.commit()
            resume_ids.add(r.id)
        except Exception as e:
            db.rollback()
            logger.warning(f"hard_filter promote failed cand={cid}: {e}")
    return resume_ids


def resume_passes_hard_filter(
    db: Session, user_id: int, job_id: int, resume_id: int
) -> bool:
    """单条快速判定: resume_id 是否在 job 的硬筛通过集合内."""
    return resume_id in hard_filter_resume_ids(db, user_id, job_id)
