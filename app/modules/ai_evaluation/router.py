"""AI 评估 API 路由"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.adapters.ai_provider import AIProvider
from app.modules.ai_evaluation.service import AIEvaluationService
from app.modules.ai_evaluation.schemas import (
    EvaluationRequest, BatchEvaluationRequest,
    EvaluationResult, BatchEvaluationResponse,
)

router = APIRouter()


def get_ai_service(db: Session = Depends(get_db)) -> AIEvaluationService:
    return AIEvaluationService(db)


@router.post("/evaluate", response_model=EvaluationResult)
async def evaluate_resume(request: EvaluationRequest, service: AIEvaluationService = Depends(get_ai_service)):
    if not settings.ai_enabled:
        raise HTTPException(status_code=400, detail="AI 功能未开启，请在设置中启用")
    return await service.evaluate_single(request.resume_id, request.job_id)


@router.post("/evaluate/batch", response_model=BatchEvaluationResponse)
async def batch_evaluate(request: BatchEvaluationRequest, service: AIEvaluationService = Depends(get_ai_service)):
    if not settings.ai_enabled:
        raise HTTPException(status_code=400, detail="AI 功能未开启，请在设置中启用")
    return await service.evaluate_batch(request.job_id, request.resume_ids)


@router.get("/status")
def ai_status():
    provider = AIProvider()
    return {
        "enabled": settings.ai_enabled,
        "configured": provider.is_configured(),
        "provider": settings.ai_provider,
        "model": settings.ai_model,
    }
