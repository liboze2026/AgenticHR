"""HITL HTTP API."""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from app.core.hitl.service import HitlService, InvalidHitlStateError, HitlCallbackError
from app.modules.auth.deps import get_current_user_id

router = APIRouter(prefix="/api/hitl", tags=["hitl"])


class _ApproveBody(BaseModel):
    note: str = ""


class _RejectBody(BaseModel):
    note: str


class _EditBody(BaseModel):
    edited_payload: dict
    note: str = ""


@router.get("/tasks")
def list_tasks(stage: str | None = None, status: str | None = None,
                limit: int = 200, offset: int = 0) -> dict:
    items = HitlService().list(stage=stage, status=status, limit=limit, offset=offset)
    pending = HitlService().count_pending(stage=stage)
    return {"items": items, "total": len(items), "pending": pending}


@router.get("/tasks/{task_id}")
def get_task(task_id: int) -> dict:
    t = HitlService().get(task_id)
    if not t:
        raise HTTPException(status_code=404, detail="task not found")
    return t


@router.post("/tasks/{task_id}/approve")
def approve(task_id: int, body: _ApproveBody, user_id: int = Depends(get_current_user_id)) -> dict:
    try:
        HitlService().approve(task_id, reviewer_id=user_id, note=body.note)
    except InvalidHitlStateError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HitlCallbackError as e:
        raise HTTPException(status_code=502, detail=f"审批已登记但业务未生效, 任务回退到待审: {e}")
    return {"status": "approved"}


@router.post("/tasks/{task_id}/reject")
def reject(task_id: int, body: _RejectBody, user_id: int = Depends(get_current_user_id)) -> dict:
    try:
        HitlService().reject(task_id, reviewer_id=user_id, note=body.note)
    except InvalidHitlStateError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "rejected"}


@router.post("/tasks/{task_id}/edit")
def edit(task_id: int, body: _EditBody, user_id: int = Depends(get_current_user_id)) -> dict:
    try:
        HitlService().edit(task_id, reviewer_id=user_id, edited_payload=body.edited_payload, note=body.note)
    except InvalidHitlStateError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HitlCallbackError as e:
        raise HTTPException(status_code=502, detail=f"修改已登记但业务未生效, 任务回退到待审: {e}")
    return {"status": "edited"}
