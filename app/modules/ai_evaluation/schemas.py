"""AI 评估输入/输出数据结构"""
from pydantic import BaseModel, Field


class EvaluationRequest(BaseModel):
    resume_id: int
    job_id: int


class BatchEvaluationRequest(BaseModel):
    job_id: int
    resume_ids: list[int] | None = Field(None, description="为空则评估该岗位所有已通过硬性筛选的简历")


class EvaluationResult(BaseModel):
    resume_id: int
    resume_name: str
    score: float
    strengths: list[str]
    risks: list[str]
    recommendation: str
    summary: str
    status: str


class BatchEvaluationResponse(BaseModel):
    job_id: int
    total: int
    succeeded: int
    failed: int
    results: list[EvaluationResult]
