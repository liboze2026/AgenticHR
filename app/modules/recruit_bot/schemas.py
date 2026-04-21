"""F3 recruit_bot 请求 / 响应 Pydantic schemas."""
from typing import Literal
from pydantic import BaseModel, Field


class ScrapedCandidate(BaseModel):
    """Edge 扩展从 Boss 推荐列表 list card 抠出的字段.

    LIST-only 策略：spec §5.2. 不开 modal，字段全部来自 list 卡片可见区.
    """
    name: str = Field(..., min_length=1, max_length=100)
    boss_id: str = Field(..., min_length=1, max_length=100)
    age: int | None = None
    education: str = ""
    grad_year: int | None = None
    work_years: int = 0
    school: str = ""
    major: str = ""
    intended_job: str = ""
    skill_tags: list[str] = Field(default_factory=list)
    school_tier_tags: list[str] = Field(default_factory=list)
    ranking_tags: list[str] = Field(default_factory=list)
    expected_salary: str = ""
    active_status: str = ""
    recommendation_reason: str = ""
    latest_work_brief: str = ""
    raw_text: str = ""
    boss_current_job_title: str = ""


class RecruitEvaluateRequest(BaseModel):
    job_id: int
    candidate: ScrapedCandidate


class RecruitDecision(BaseModel):
    """后端对单候选人的决策."""
    decision: Literal[
        "should_greet",
        "skipped_already_greeted",
        "rejected_low_score",
        "blocked_daily_cap",
        "error_no_competency",
    ]
    resume_id: int | None = None
    score: int | None = None
    threshold: int | None = None
    reason: str = ""


class GreetRecordRequest(BaseModel):
    resume_id: int
    success: bool
    error_msg: str = ""


class UsageInfo(BaseModel):
    used: int
    cap: int
    remaining: int


class DailyCapUpdateRequest(BaseModel):
    cap: int = Field(..., ge=0, le=10000)
