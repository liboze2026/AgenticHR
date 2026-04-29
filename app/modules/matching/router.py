"""F2 匹配 REST API."""
import json
import logging
from typing import Optional
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.modules.auth.deps import get_current_user_id
from app.modules.matching.hashing import compute_competency_hash, compute_weights_hash
from app.modules.matching.weights import get_effective_weights
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


class _NormalizeError(Exception):
    """promote 失败的内部错误，区分 404（不存在）和 500（服务端错误）。"""
    pass


def _normalize_resume_id(db: Session, input_id: int, user_id: int) -> int | None:
    """翻译 candidate.id → Resume.id（按需 promote）；不存在返 None；
    BUG-072 修复：promote 抛异常时抛 _NormalizeError，调用方区分 500 vs 404。"""
    from app.modules.im_intake.candidate_model import IntakeCandidate
    cand = db.query(IntakeCandidate).filter_by(id=input_id, user_id=user_id).first()
    if cand:
        if cand.promoted_resume_id:
            existing = db.query(Resume).filter_by(id=cand.promoted_resume_id).first()
            if existing and existing.user_id == user_id:
                return existing.id
        try:
            from app.modules.im_intake.promote import promote_to_resume
            r = promote_to_resume(db, cand, user_id=user_id)
            db.commit()
            return r.id
        except Exception as _e:
            db.rollback()
            raise _NormalizeError(str(_e))
    resume = db.query(Resume).filter_by(id=input_id, user_id=user_id).first()
    if resume:
        return resume.id
    return None


def _hard_filter_resume_ids(db: Session, user_id: int, job_id: int) -> set[int]:
    """硬筛通过的 candidate → 翻译为 Resume.id 集合 (按需 promote).
    用于 "五维能力筛选" 通道：仅对硬筛通过的人跑 F2 评分。
    翻译失败的 candidate (promote 抛异常) 静默跳过, 不阻塞批量。
    """
    from app.modules.resume.intake_view_service import (
        _complete_query, list_matched_for_job,
    )
    # 复用 list_matched_for_job 的过滤规则 (四齐全 + 学历 + 院校等级)
    matched_dicts = list_matched_for_job(db, user_id=user_id, job_id=job_id)
    cand_ids = [d["id"] for d in matched_dicts]
    resume_ids: set[int] = set()
    for cid in cand_ids:
        try:
            rid = _normalize_resume_id(db, cid, user_id)
            if rid is not None:
                resume_ids.add(rid)
        except _NormalizeError:
            # promote 失败 → 跳过, 这条候选人本轮不参与 F2 评分
            continue
    return resume_ids


def _resolve_or_404(db: Session, input_id: int, user_id: int) -> int:
    """统一鉴权 + 翻译。BUG-056 修复：他人资源与不存在均返 404。"""
    try:
        rid = _normalize_resume_id(db, input_id, user_id)
    except _NormalizeError as e:
        raise HTTPException(status_code=500, detail="无法落库简历，请稍后重试")
    if rid is None:
        raise HTTPException(status_code=404, detail="简历不存在")
    return rid


@router.post("/score", response_model=MatchingResultResponse)
async def score_pair(req: ScoreRequest, db: Session = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    _require_matching_enabled()
    real_resume_id = _resolve_or_404(db, req.resume_id, user_id)
    job = db.query(Job).filter_by(id=req.job_id).first()
    if not job or job.user_id != user_id:
        raise HTTPException(status_code=404, detail="岗位不存在")
    service = MatchingService(db)
    try:
        return await service.score_pair(real_resume_id, req.job_id, triggered_by="T4")
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
    user_id: int = Depends(get_current_user_id),
):
    _require_matching_enabled()
    if not job_id and not resume_id:
        raise HTTPException(status_code=400, detail="need job_id or resume_id")

    q = db.query(MatchingResult)
    if job_id:
        job = db.query(Job).filter_by(id=job_id).first()
        if not job or job.user_id != user_id:
            raise HTTPException(status_code=404, detail="岗位不存在")
        q = q.filter_by(job_id=job_id).order_by(MatchingResult.total_score.desc())
    if resume_id:
        resume_id = _resolve_or_404(db, resume_id, user_id)
        q = q.filter_by(resume_id=resume_id).order_by(MatchingResult.total_score.desc())

    raw_rows = q.all()
    # 防御性过滤：剔除引用已删除 Resume / Job 的孤儿行（matching_results 无 FK）
    # BUG-071 修复：补上 IntakeCandidate 状态过滤；abandoned/timed_out candidate 对应的
    # promoted Resume 也应剔除，避免出现"matching 显示但前端列表已过滤"的不一致。
    if raw_rows:
        from app.modules.im_intake.candidate_model import IntakeCandidate
        live_resume_ids = {
            r.id for r in db.query(Resume.id).filter(
                Resume.id.in_({m.resume_id for m in raw_rows}),
                Resume.status != "rejected",
            ).all()
        }
        # 进一步剔除对应 candidate 已 abandoned/timed_out 的 Resume.id
        if live_resume_ids:
            dead_via_candidate = {
                cid for (cid,) in db.query(IntakeCandidate.promoted_resume_id).filter(
                    IntakeCandidate.promoted_resume_id.in_(live_resume_ids),
                    IntakeCandidate.intake_status.in_(["abandoned", "timed_out"]),
                ).all()
            }
            live_resume_ids -= dead_via_candidate
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

    # 按 job 分组算 current hash — 每个 job 用自己的 effective weights
    current_hashes = {}   # job_id → (competency_hash, weights_hash)
    for jid, j in jobs.items():
        current_hashes[jid] = (
            compute_competency_hash(j.competency_model or {}),
            compute_weights_hash(get_effective_weights(j)),
        )

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
            job_action=r.job_action,
            stale=(r.competency_hash != current_c or r.weights_hash != current_w),
            scored_at=r.scored_at,
        ))
    return MatchingResultListResponse(
        total=total, page=page, page_size=page_size, items=items,
    )


from fastapi import BackgroundTasks
from pydantic import BaseModel as _PydanticBaseModel
from app.modules.matching.service import (
    _new_task, _get_task, _prune_stale_tasks,
    recompute_job_with_fresh_session, recompute_resume_with_fresh_session,
)


class _ActionBody(_PydanticBaseModel):
    action: str | None = None  # 'passed' / 'rejected' / null


@router.patch("/results/{result_id}/action")
def set_action(result_id: int, body: _ActionBody, db: Session = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    _require_matching_enabled()
    row = db.query(MatchingResult).filter_by(id=result_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="matching result not found")
    # BUG-056 修复：他人资源与不存在均返 404，不暴露存在性
    owner_resume = db.query(Resume).filter_by(id=row.resume_id).first()
    if not owner_resume or owner_resume.user_id != user_id:
        raise HTTPException(status_code=404, detail="matching result not found")
    if body.action not in (None, "passed", "rejected"):
        raise HTTPException(status_code=400, detail="action must be passed/rejected/null")
    row.job_action = body.action
    db.commit()
    return {"id": row.id, "job_action": row.job_action}


@router.get("/passed-resumes/{job_id}")
def list_passed_for_job(job_id: int, db: Session = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    """岗位匹配候选人: 四项齐全 ∩ 学历门槛 ∩ 院校等级门槛 (PR4)"""
    job = db.query(Job).filter_by(id=job_id).first()
    if not job or job.user_id != user_id:
        raise HTTPException(status_code=404, detail="岗位不存在")
    from app.modules.resume.intake_view_service import list_matched_for_job
    return list_matched_for_job(db, user_id=user_id, job_id=job_id)


@router.post("/recompute")
async def post_recompute(
    req: RecomputeRequest,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    _require_matching_enabled()
    _prune_stale_tasks()
    if not req.job_id and not req.resume_id:
        raise HTTPException(status_code=400, detail="need job_id or resume_id")

    if req.job_id:
        # BUG-006 / 限定 job 归属
        job = db.query(Job).filter_by(id=req.job_id).first()
        if not job or job.user_id != user_id:
            raise HTTPException(status_code=404, detail="岗位不存在")
        # 硬筛串联 (五维能力筛选通道): 用 list_matched_for_job 的 candidate ID 集合
        # 翻译成 Resume.id, 仅对硬筛通过的人跑 F2, 避免给被硬筛拒掉的人浪费 LLM token.
        pre_filter_resume_ids = _hard_filter_resume_ids(db, user_id, req.job_id)
        total = len(pre_filter_resume_ids)
        task_id = _new_task(total)
        background.add_task(
            recompute_job_with_fresh_session,
            req.job_id, task_id, user_id,
            pre_filter_resume_ids=pre_filter_resume_ids,
        )
        return {"task_id": task_id, "total": total}

    real_resume_id = _resolve_or_404(db, req.resume_id, user_id)
    total = db.query(Job).filter(
        Job.is_active == True,
        Job.competency_model_status == "approved",
    ).count()
    task_id = _new_task(total)
    background.add_task(recompute_resume_with_fresh_session, real_resume_id, task_id)
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
