"""F2 匹配 REST API."""
import json
import logging
from typing import Optional
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.config import settings
from app.core.settings.router import _load as _load_scoring_weights
from app.database import get_db
from app.modules.matching.hashing import compute_competency_hash, compute_weights_hash
from app.modules.matching.models import MatchingResult
from app.modules.matching.schemas import (
    EvidenceItem,
    MatchingResultResponse, MatchingResultListResponse,
    ScoreRequest, RecomputeRequest, RecomputeStatus,
)
from app.modules.matching.service import MatchingService
from app.modules.resume.models import Resume
from app.modules.screening.models import Job

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/matching", tags=["matching"])


def _require_matching_enabled():
    if not getattr(settings, "matching_enabled", True):
        raise HTTPException(status_code=503, detail="matching feature disabled")


@router.post("/score", response_model=MatchingResultResponse)
async def score_pair(req: ScoreRequest, db: Session = Depends(get_db)):
    _require_matching_enabled()
    service = MatchingService(db)
    try:
        return await service.score_pair(req.resume_id, req.job_id, triggered_by="T4")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/results", response_model=MatchingResultListResponse)
def list_results(
    job_id: Optional[int] = None,
    resume_id: Optional[int] = None,
    tag: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    _require_matching_enabled()
    if not job_id and not resume_id:
        raise HTTPException(status_code=400, detail="need job_id or resume_id")

    q = db.query(MatchingResult)
    if job_id:
        q = q.filter_by(job_id=job_id).order_by(MatchingResult.total_score.desc())
    if resume_id:
        q = q.filter_by(resume_id=resume_id).order_by(MatchingResult.total_score.desc())

    raw_rows = q.all()
    # 防御性过滤：剔除引用已删除 Resume / Job 的孤儿行（matching_results 无 FK）
    if raw_rows:
        live_resume_ids = {
            r.id for r in db.query(Resume.id).filter(
                Resume.id.in_({m.resume_id for m in raw_rows})
            ).all()
        }
        live_job_ids = {
            j.id for j in db.query(Job.id).filter(
                Job.id.in_({m.job_id for m in raw_rows})
            ).all()
        }
        all_rows = [
            r for r in raw_rows
            if r.resume_id in live_resume_ids and r.job_id in live_job_ids
        ]
    else:
        all_rows = []
    if tag:
        all_rows = [r for r in all_rows if tag in json.loads(r.tags or "[]")]

    total = len(all_rows)
    start = (page - 1) * page_size
    rows = all_rows[start: start + page_size]

    # 批量预取 resume/job 信息 + 当前 hash
    resume_ids = {r.resume_id for r in rows}
    job_ids = {r.job_id for r in rows}
    resumes = {r.id: r for r in db.query(Resume).filter(Resume.id.in_(resume_ids)).all()}
    jobs = {j.id: j for j in db.query(Job).filter(Job.id.in_(job_ids)).all()}

    # 按 job 分组算 current hash
    current_hashes = {}   # job_id → (competency_hash, weights_hash)
    weights_hash = compute_weights_hash(_load_scoring_weights())
    for jid, j in jobs.items():
        current_hashes[jid] = (compute_competency_hash(j.competency_model or {}), weights_hash)

    items = []
    for r in rows:
        resume = resumes.get(r.resume_id)
        job = jobs.get(r.job_id)
        current_c, current_w = current_hashes.get(r.job_id, (r.competency_hash, r.weights_hash))
        evidence_dict = json.loads(r.evidence or "{}")
        items.append(MatchingResultResponse(
            id=r.id, resume_id=r.resume_id,
            resume_name=resume.name if resume else "",
            job_id=r.job_id, job_title=job.title if job else "",
            total_score=r.total_score, skill_score=r.skill_score,
            experience_score=r.experience_score, seniority_score=r.seniority_score,
            education_score=r.education_score, industry_score=r.industry_score,
            hard_gate_passed=bool(r.hard_gate_passed),
            missing_must_haves=json.loads(r.missing_must_haves or "[]"),
            evidence={k: [EvidenceItem(**e) for e in v] for k, v in evidence_dict.items()},
            tags=json.loads(r.tags or "[]"),
            stale=(r.competency_hash != current_c or r.weights_hash != current_w),
            scored_at=r.scored_at,
        ))
    return MatchingResultListResponse(
        total=total, page=page, page_size=page_size, items=items,
    )


from fastapi import BackgroundTasks
from app.modules.matching.service import (
    _new_task, _get_task, _prune_stale_tasks,
    recompute_job_with_fresh_session, recompute_resume_with_fresh_session,
)


@router.post("/recompute")
async def post_recompute(
    req: RecomputeRequest,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
):
    _require_matching_enabled()
    _prune_stale_tasks()
    if not req.job_id and not req.resume_id:
        raise HTTPException(status_code=400, detail="need job_id or resume_id")

    if req.job_id:
        total = db.query(Resume).filter_by(ai_parsed="yes").count()
        task_id = _new_task(total)
        background.add_task(recompute_job_with_fresh_session, req.job_id, task_id)
        return {"task_id": task_id, "total": total}

    total = db.query(Job).filter(
        Job.is_active == True,
        Job.competency_model_status == "approved",
    ).count()
    task_id = _new_task(total)
    background.add_task(recompute_resume_with_fresh_session, req.resume_id, task_id)
    return {"task_id": task_id, "total": total}


@router.get("/recompute/status/{task_id}", response_model=RecomputeStatus)
def get_recompute_status(task_id: str):
    task = _get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    return RecomputeStatus(
        task_id=task["task_id"], total=task["total"],
        completed=task["completed"], failed=task["failed"],
        running=task["running"], current=task.get("current", ""),
    )
