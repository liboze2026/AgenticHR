"""岗位管理与筛选 API 路由"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.auth.deps import get_current_user_id
from app.modules.screening.service import ScreeningService
from app.modules.screening.schemas import (
    JobCreate, JobUpdate, JobResponse, JobListResponse, ScreeningResponse,
)
from app.modules.scheduling.models import Interview
from app.core.competency.extractor import extract_competency, ExtractionFailedError
from app.core.hitl.service import HitlService
from app.modules.screening.competency_service import apply_competency_to_job

router = APIRouter()


def get_screening_service(db: Session = Depends(get_db)) -> ScreeningService:
    return ScreeningService(db)


@router.post("/jobs", response_model=JobResponse, status_code=201)
def create_job(
    data: JobCreate,
    service: ScreeningService = Depends(get_screening_service),
    user_id: int = Depends(get_current_user_id),
):
    job = service.create_job(data)
    job.user_id = user_id
    service.db.commit()
    service.db.refresh(job)
    return job


@router.get("/jobs", response_model=JobListResponse)
def list_jobs(
    active_only: bool = False,
    service: ScreeningService = Depends(get_screening_service),
    user_id: int = Depends(get_current_user_id),
):
    return service.list_jobs(active_only=active_only, user_id=user_id)


@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(
    job_id: int,
    service: ScreeningService = Depends(get_screening_service),
    user_id: int = Depends(get_current_user_id),
):
    job = service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="岗位不存在")
    if job.user_id != user_id:
        raise HTTPException(status_code=403, detail="无权访问该岗位")
    return job


@router.patch("/jobs/{job_id}", response_model=JobResponse)
def update_job(
    job_id: int,
    data: JobUpdate,
    service: ScreeningService = Depends(get_screening_service),
    user_id: int = Depends(get_current_user_id),
):
    job = service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="岗位不存在")
    if job.user_id != user_id:
        raise HTTPException(status_code=403, detail="无权修改该岗位")
    updated = service.update_job(job_id, data)
    return updated


@router.delete("/jobs/{job_id}", status_code=204)
def delete_job(
    job_id: int,
    db: Session = Depends(get_db),
    service: ScreeningService = Depends(get_screening_service),
    user_id: int = Depends(get_current_user_id),
):
    job = service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="岗位不存在")
    if job.user_id != user_id:
        raise HTTPException(status_code=403, detail="无权删除该岗位")
    linked = db.query(Interview).filter(
        Interview.job_id == job_id,
        Interview.status != "cancelled",
    ).count()
    if linked > 0:
        raise HTTPException(
            status_code=409,
            detail=f"该岗位下有 {linked} 场待面试，请先处理后再删除"
        )
    service.delete_job(job_id)


@router.post("/jobs/{job_id}/screen", response_model=ScreeningResponse)
def screen_resumes(
    job_id: int,
    resume_ids: list[int] | None = None,
    service: ScreeningService = Depends(get_screening_service),
    user_id: int = Depends(get_current_user_id),
):
    job = service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="岗位不存在")
    if job.user_id != user_id:
        raise HTTPException(status_code=403, detail="无权操作该岗位")
    return service.screen_resumes(job_id, resume_ids)


class _ManualBody(BaseModel):
    flat_fields: dict


@router.post("/jobs/{job_id}/competency/extract")
async def extract_job_competency(job_id: int):
    """触发 LLM 抽取能力模型. 成功 → draft + HITL; 失败 → 降级扁平表单."""
    from app.database import SessionLocal
    from app.modules.screening.models import Job

    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        jd_text = job.jd_text or ""
    finally:
        db.close()

    if not jd_text.strip():
        raise HTTPException(status_code=400, detail="jd_text 为空, 请先填 JD 原文")

    try:
        model = await extract_competency(jd_text=jd_text, job_id=job_id)
    except ExtractionFailedError:
        return {"status": "failed", "fallback": "flat_form"}

    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        job.competency_model = model.model_dump(mode="json")
        job.competency_model_status = "draft"
        db.commit()
    finally:
        db.close()

    hitl_id = HitlService().create(
        f_stage="F1_competency_review",
        entity_type="job",
        entity_id=job_id,
        payload=model.model_dump(mode="json"),
    )
    return {"status": "draft", "hitl_task_id": hitl_id}


@router.get("/jobs/{job_id}/competency")
def get_job_competency(job_id: int):
    from app.database import SessionLocal
    from app.modules.screening.models import Job
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        return {
            "competency_model": job.competency_model,
            "status": job.competency_model_status,
        }
    finally:
        db.close()


@router.post("/jobs/{job_id}/competency/manual")
def manual_competency(job_id: int, body: _ManualBody):
    """LLM 失败后 HR 手填扁平字段, 服务端翻译为最简 CompetencyModel, 直接 approved."""
    f = body.flat_fields
    skills_csv = f.get("required_skills", "") or ""
    hard_skills = [
        {"name": s.strip(), "weight": 5, "level": "熟练", "must_have": True}
        for s in skills_csv.split(",") if s.strip()
    ]
    model_dict = {
        "schema_version": 1,
        "hard_skills": hard_skills,
        "soft_skills": [],
        "experience": {
            "years_min": int(f.get("work_years_min") or 0),
            "years_max": int(f.get("work_years_max")) if f.get("work_years_max") is not None else None,
            "industries": [],
            "company_scale": None,
        },
        "education": {
            "min_level": f.get("education_min") or "本科",
            "preferred_level": None,
            "prestigious_bonus": False,
        },
        "job_level": "",
        "bonus_items": [],
        "exclusions": [],
        "assessment_dimensions": [],
        "source_jd_hash": "manual_fallback",
        "extracted_at": datetime.now(timezone.utc).isoformat(),
    }
    apply_competency_to_job(job_id, model_dict)

    from app.core.audit.logger import log_event
    log_event(
        f_stage="F1_competency_review",
        action="manual_fallback",
        entity_type="job",
        entity_id=job_id,
        input_payload=body.flat_fields,
        output_payload=model_dict,
    )
    return {"status": "approved"}
