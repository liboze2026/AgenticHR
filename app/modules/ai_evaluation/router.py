"""AI 评估 API (F5 will extend)."""
from fastapi import APIRouter, HTTPException

from app.config import settings
from app.adapters.ai_provider import AIProvider

router = APIRouter()


@router.post("/evaluate")
async def deprecated_evaluate_single():
    raise HTTPException(
        status_code=410,
        detail={
            "msg": "/api/ai-evaluation/evaluate has been removed in favor of F2 structured matching.",
            "migrate_to": "/api/matching/score",
        },
    )


@router.post("/evaluate/batch")
async def deprecated_evaluate_batch():
    raise HTTPException(
        status_code=410,
        detail={
            "msg": "/api/ai-evaluation/evaluate/batch has been removed in favor of F2 structured matching.",
            "migrate_to": "/api/matching/recompute",
        },
    )


@router.get("/status")
def ai_status():
    provider = AIProvider()
    return {
        "enabled": settings.ai_enabled,
        "configured": provider.is_configured(),
        "provider": settings.ai_provider,
        "model": settings.ai_model,
    }
