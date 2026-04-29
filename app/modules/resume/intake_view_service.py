"""简历库与岗位匹配候选人视图：从 IntakeCandidate 构建（四项齐全谓词）

PR4 新增。简历库 == 匹配候选人母集；匹配候选人额外按岗位学历门槛过滤。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.im_intake.models import IntakeSlot
from app.modules.im_intake.school_tier import meets_education, meets_school_tier
from app.modules.im_intake.templates import HARD_SLOT_KEYS
from app.modules.screening.models import Job


def _slot_complete_subquery(db: Session):
    """子查询: 每个候选人已填(value 非空)的 hard slot 数量"""
    return (
        db.query(
            IntakeSlot.candidate_id.label("cid"),
            func.count(IntakeSlot.id).label("filled_count"),
        )
        .filter(IntakeSlot.slot_key.in_(HARD_SLOT_KEYS))
        .filter(IntakeSlot.value.isnot(None))
        .filter(IntakeSlot.value != "")
        .group_by(IntakeSlot.candidate_id)
        .subquery()
    )


def _complete_query(db: Session, user_id: int):
    """简历库基础查询: 四项齐全(三 hard slot + PDF) 且属于该用户"""
    sub = _slot_complete_subquery(db)
    return (
        db.query(IntakeCandidate)
        .outerjoin(sub, IntakeCandidate.id == sub.c.cid)
        .filter(IntakeCandidate.user_id == user_id)
        .filter(IntakeCandidate.pdf_path.isnot(None))
        .filter(IntakeCandidate.pdf_path != "")
        .filter(sub.c.filled_count == len(HARD_SLOT_KEYS))
    )


def candidate_to_resume_dict(c: IntakeCandidate, db: Session | None = None) -> dict[str, Any]:
    """IntakeCandidate -> ResumeResponse-shape dict (前端零改动)
    BUG-068 修复：status 不再硬编码 'passed'；abandoned/timed_out 候选人映射到 'rejected'。
    BUG-086 修复：reject_reason 从 promoted Resume 拉取（IntakeCandidate 无此列）。"""
    # status 映射
    intake_st = c.intake_status or ""
    if intake_st in ("abandoned", "timed_out"):
        status = "rejected"
    elif intake_st == "complete":
        status = "passed"
    else:
        status = "pending"

    # reject_reason / Resume.status 从 promoted Resume 拉取
    reject_reason = ""
    if db is not None and c.promoted_resume_id:
        from app.modules.resume.models import Resume as _R
        r = db.query(_R).filter_by(id=c.promoted_resume_id).first()
        if r:
            if r.status == "rejected":
                status = "rejected"
            elif r.status == "passed" and intake_st == "complete":
                status = "passed"
            reject_reason = r.reject_reason or ""

    return {
        "id": c.id,
        "name": c.name or "",
        "phone": c.phone or "",
        "email": c.email or "",
        "education": c.education or "",
        "bachelor_school": c.bachelor_school or "",
        "master_school": c.master_school or "",
        "phd_school": c.phd_school or "",
        "qr_code_path": c.qr_code_path or "",
        "work_years": c.work_years or 0,
        "expected_salary_min": c.expected_salary_min or 0.0,
        "expected_salary_max": c.expected_salary_max or 0.0,
        "job_intention": c.job_intention or "",
        "skills": c.skills or "",
        "work_experience": c.work_experience or "",
        "project_experience": c.project_experience or "",
        "self_evaluation": c.self_evaluation or "",
        "source": c.source or "",
        "raw_text": c.raw_text or "",
        "pdf_path": c.pdf_path or "",
        "status": status,
        "ai_parsed": c.ai_parsed or "no",
        "ai_score": c.ai_score,
        "ai_summary": c.ai_summary or "",
        "reject_reason": reject_reason,
        "seniority": c.seniority or "",
        "intake_status": c.intake_status or "complete",
        "boss_id": c.boss_id or "",
        "school_tier": c.school_tier or "",
        "created_at": c.created_at or datetime.utcnow(),
        "updated_at": c.updated_at or datetime.utcnow(),
    }


def list_resume_library(
    db: Session,
    user_id: int,
    page: int = 1,
    page_size: int = 10,
    keyword: str | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    """简历库列表: 四项齐全的候选人"""
    query = _complete_query(db, user_id)

    if source:
        query = query.filter(IntakeCandidate.source == source)

    if keyword:
        _kw = keyword.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
        pattern = f"%{_kw}%"
        query = query.filter(
            or_(
                IntakeCandidate.name.like(pattern, escape="\\"),
                IntakeCandidate.skills.like(pattern, escape="\\"),
                IntakeCandidate.job_intention.like(pattern, escape="\\"),
                IntakeCandidate.work_experience.like(pattern, escape="\\"),
                IntakeCandidate.raw_text.like(pattern, escape="\\"),
            )
        )

    total = query.count()
    items = (
        query.order_by(IntakeCandidate.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [candidate_to_resume_dict(c, db) for c in items],
    }


def list_matched_for_job(
    db: Session,
    user_id: int,
    job_id: int,
) -> list[dict[str, Any]]:
    """岗位匹配候选人: 简历库 ∩ 岗位学历门槛"""
    job = db.query(Job).filter_by(id=job_id, user_id=user_id).first()
    if not job:
        return []

    edu_min = job.education_min or ""
    tier_min = (getattr(job, "school_tier_min", "") or "")

    candidates = _complete_query(db, user_id).all()
    matched = [
        c for c in candidates
        if meets_education(c.education or "", edu_min)
        and meets_school_tier(c.school_tier or "", tier_min)
    ]
    matched.sort(key=lambda c: c.created_at or datetime.min, reverse=True)
    return [candidate_to_resume_dict(c, db) for c in matched]
