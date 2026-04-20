"""系统全局配置 — 候选人评分维度权重."""
import json
import os
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

router = APIRouter(prefix="/api/settings", tags=["settings"])

_CONFIG_PATH = Path(__file__).parent.parent.parent.parent / "data" / "scoring_weights.json"

_DEFAULTS = {
    "skill_match": 35,
    "experience": 30,
    "seniority": 15,
    "education": 10,
    "industry": 10,
}


class ScoringWeights(BaseModel):
    skill_match: int = 35
    experience: int = 30
    seniority: int = 15
    education: int = 10
    industry: int = 10

    @field_validator("skill_match", "experience", "seniority", "education", "industry")
    @classmethod
    def check_range(cls, v):
        if not (0 <= v <= 100):
            raise ValueError("每项权重必须在 0–100 之间")
        return v

    def total(self) -> int:
        return self.skill_match + self.experience + self.seniority + self.education + self.industry


def _load() -> dict:
    try:
        if _CONFIG_PATH.exists():
            return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return _DEFAULTS.copy()


def _save(data: dict) -> None:
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


@router.get("/scoring-weights", response_model=ScoringWeights)
def get_scoring_weights():
    return _load()


@router.put("/scoring-weights", response_model=ScoringWeights)
def update_scoring_weights(body: ScoringWeights):
    if body.total() != 100:
        raise HTTPException(status_code=422, detail=f"各维度权重之和必须为 100，当前为 {body.total()}")
    data = body.model_dump()
    _save(data)
    return data
