"""Boss 自动化 API 路由"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.auth.deps import get_current_user_id
from app.modules.boss_automation.schemas import (
    AutoGreetRequest,
    AutoGreetResponse,
    CollectResumesResponse,
    BossStatusResponse,
)
from app.modules.boss_automation.service import BossAutomationService

router = APIRouter()


def get_boss_service(db: Session = Depends(get_db)) -> BossAutomationService:
    # 实际使用时可根据 settings.boss_adapter 注入不同的适配器
    return BossAutomationService(db, adapter=None)


@router.post("/greet", response_model=AutoGreetResponse)
async def auto_greet(
    request: AutoGreetRequest,
    service: BossAutomationService = Depends(get_boss_service),
    user_id: int = Depends(get_current_user_id),  # BUG-042
):
    return await service.auto_greet(
        job_id=request.job_id,
        message=request.message,
        max_count=request.max_count,
        user_id=user_id,
    )


@router.post("/collect", response_model=CollectResumesResponse)
async def collect_resumes(
    service: BossAutomationService = Depends(get_boss_service),
    user_id: int = Depends(get_current_user_id),  # BUG-042
):
    return await service.collect_resumes(user_id=user_id)


@router.get("/status", response_model=BossStatusResponse)
async def get_status(
    service: BossAutomationService = Depends(get_boss_service),
    user_id: int = Depends(get_current_user_id),  # BUG-042
):
    return await service.get_status(user_id=user_id)
