"""F2 API 请求/响应 Pydantic schemas."""
from datetime import datetime
from pydantic import BaseModel, Field


class EvidenceItem(BaseModel):
    text: str
    source: str = ""
    offset: list[int] | None = None


class MatchingResultResponse(BaseModel):
    id: int
    resume_id: int
    resume_name: str = ""
    job_id: int
    job_title: str = ""

    total_score: float
    skill_score: float
    experience_score: float
    seniority_score: float
    education_score: float
    industry_score: float

    hard_gate_passed: bool
    missing_must_haves: list[str] = []

    evidence: dict[str, list[EvidenceItem]] = Field(default_factory=dict)
    tags: list[str] = []

    stale: bool = False
    scored_at: datetime


class MatchingResultListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[MatchingResultResponse]


class ScoreRequest(BaseModel):
    resume_id: int
    job_id: int


class RecomputeRequest(BaseModel):
    job_id: int | None = None
    resume_id: int | None = None


class RecomputeStatus(BaseModel):
    task_id: str
    total: int
    completed: int
    failed: int
    running: bool
    current: str = ""
