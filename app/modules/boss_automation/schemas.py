"""Boss 自动化模块的请求/响应模型"""
from pydantic import BaseModel, Field


class AutoGreetRequest(BaseModel):
    """自动打招呼请求"""
    job_id: str = ""
    message: str = ""
    max_count: int = Field(default=10, ge=1, le=50)


class GreetedCandidate(BaseModel):
    """被打招呼的候选人信息"""
    name: str
    boss_id: str
    success: bool


class AutoGreetResponse(BaseModel):
    """自动打招呼响应"""
    total_found: int = 0
    greeted_count: int = 0
    candidates: list[GreetedCandidate] = []
    message: str = ""


class CollectedResume(BaseModel):
    """收集到的简历信息"""
    name: str
    boss_id: str
    has_pdf: bool
    resume_id: int | None = None


class CollectResumesResponse(BaseModel):
    """收集简历响应"""
    collected_count: int = 0
    resumes: list[CollectedResume] = []
    message: str = ""


class BossStatusResponse(BaseModel):
    """Boss 适配器状态响应"""
    available: bool = False
    adapter_type: str = ""
    operations_today: int = 0
    max_operations_per_day: int = 0
    message: str = ""
