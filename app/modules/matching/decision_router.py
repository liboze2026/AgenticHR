"""spec 0429-D — 岗位 × 候选人 决策 REST API"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.auth.deps import get_current_user_id
from app.modules.matching.decision_service import (
    DecisionError,
    set_decision,
)


router = APIRouter(prefix="/api/jobs", tags=["matching"])


class _DecisionBody(BaseModel):
    action: Optional[str] = None  # 'passed' / 'rejected' / null


_ERR_TO_STATUS = {
    "job_not_found": 404,
    "candidate_not_found": 404,
    "invalid_action": 400,
}

_ERR_TO_MSG = {
    "job_not_found": "岗位不存在",
    "candidate_not_found": "候选人不存在",
    "invalid_action": "action 必须是 passed/rejected/null",
}


@router.patch("/{job_id}/candidates/{candidate_id}/decision")
def patch_decision(
    job_id: int,
    candidate_id: int,
    body: _DecisionBody,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    try:
        row = set_decision(
            db,
            user_id=user_id,
            job_id=job_id,
            candidate_id=candidate_id,
            action=body.action,
        )
    except DecisionError as e:
        status = _ERR_TO_STATUS.get(e.code, 500)
        msg = _ERR_TO_MSG.get(e.code, e.code)
        raise HTTPException(status_code=status, detail=msg)
    return {
        "job_id": job_id,
        "candidate_id": candidate_id,
        "action": row.action if row else None,
        "decided_at": row.decided_at.isoformat() if row else None,
    }
