"""spec 0429-D — 岗位 × 候选人 人工决策 service。

set/clear/list 决策, 校验 job + candidate 归属, candidate × job 维度。
"""
from __future__ import annotations

from typing import Literal, Optional

from sqlalchemy.orm import Session

from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.matching.decision_model import JobCandidateDecision
from app.modules.screening.models import Job


ALLOWED_ACTIONS = ("passed", "rejected")


class DecisionError(Exception):
    """业务异常: not_found / invalid_action。code 字段供 router 转 HTTP 状态。"""

    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


def _check_job_owner(db: Session, job_id: int, user_id: int) -> Job:
    job = db.query(Job).filter_by(id=job_id, user_id=user_id).first()
    if not job:
        raise DecisionError("job_not_found")
    return job


def _check_candidate_owner(
    db: Session, candidate_id: int, user_id: int
) -> IntakeCandidate:
    cand = (
        db.query(IntakeCandidate)
        .filter_by(id=candidate_id, user_id=user_id)
        .first()
    )
    if not cand:
        raise DecisionError("candidate_not_found")
    return cand


def set_decision(
    db: Session,
    user_id: int,
    job_id: int,
    candidate_id: int,
    action: Optional[str],
) -> Optional[JobCandidateDecision]:
    """设/改/清决策。

    action='passed'|'rejected' → upsert 行。
    action=None → 删除已有行 (无行也 OK, 幂等)。

    raise DecisionError('job_not_found' | 'candidate_not_found' | 'invalid_action')
    """
    _check_job_owner(db, job_id, user_id)
    _check_candidate_owner(db, candidate_id, user_id)

    existing = (
        db.query(JobCandidateDecision)
        .filter_by(job_id=job_id, candidate_id=candidate_id)
        .first()
    )

    if action is None:
        if existing:
            db.delete(existing)
            db.commit()
        return None

    if action not in ALLOWED_ACTIONS:
        raise DecisionError("invalid_action")

    if existing:
        existing.action = action
        db.commit()
        db.refresh(existing)
        return existing

    row = JobCandidateDecision(
        user_id=user_id,
        job_id=job_id,
        candidate_id=candidate_id,
        action=action,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_decisions_map_for_job(
    db: Session, user_id: int, job_id: int
) -> dict[int, str]:
    """返 {candidate_id: action} for 该 job + user。"""
    rows = (
        db.query(JobCandidateDecision)
        .filter_by(user_id=user_id, job_id=job_id)
        .all()
    )
    return {r.candidate_id: r.action for r in rows}


def get_decision(
    db: Session, user_id: int, job_id: int, candidate_id: int
) -> Optional[JobCandidateDecision]:
    return (
        db.query(JobCandidateDecision)
        .filter_by(user_id=user_id, job_id=job_id, candidate_id=candidate_id)
        .first()
    )
