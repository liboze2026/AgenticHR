"""岗位管理与筛选 API 路由"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.auth.deps import get_current_user_id
from app.modules.screening.service import ScreeningService
from app.modules.screening.schemas import (
    JobCreate, JobUpdate, JobResponse, JobListResponse, ScreeningResponse,
)
from app.modules.scheduling.models import Interview

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
