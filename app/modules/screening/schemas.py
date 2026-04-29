"""岗位筛选输入/输出数据结构"""
from datetime import datetime
from pydantic import BaseModel, Field, model_validator


class JobCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    department: str = Field(default="", max_length=100)
    education_min: str = Field(default="", max_length=50)
    school_tier_min: str = Field(default="", max_length=20, description="院校等级要求: ''/qs_top200/211/985")
    work_years_min: int = Field(default=0, ge=0)
    work_years_max: int = Field(default=99, ge=0)
    salary_min: float = Field(default=0, ge=0)
    salary_max: float = Field(default=0, ge=0)
    required_skills: str = Field(default="", description="逗号分��")
    soft_requirements: str = Field(default="")
    greeting_templates: str = Field(default="", description="竖线分隔多条话术")
    jd_text: str = Field(default="", description="JD 原文")
    competency_model: dict | None = Field(default=None, description="能力模型 JSON")
    competency_model_status: str = Field(default="none")
    scoring_weights: dict | None = Field(default=None, description="岗位自定义评分权重（5 维度，总和 100）")
    batch_collect_criteria: dict | None = None

    @model_validator(mode='after')
    def validate_ranges(self):
        if self.work_years_max < self.work_years_min:
            raise ValueError('最大工作年限不能小于最小工作年限')
        if self.salary_max and self.salary_min and self.salary_max < self.salary_min:
            raise ValueError('最高薪资不能低于最低薪��')
        return self


class JobUpdate(BaseModel):
    title: str | None = None
    department: str | None = None
    education_min: str | None = None
    school_tier_min: str | None = None
    work_years_min: int | None = None
    work_years_max: int | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    required_skills: str | None = None
    soft_requirements: str | None = None
    greeting_templates: str | None = None
    is_active: bool | None = None
    jd_text: str | None = None
    competency_model: dict | None = None
    competency_model_status: str | None = None
    scoring_weights: dict | None = None
    batch_collect_criteria: dict | None = None

    @model_validator(mode='after')
    def validate_ranges(self):
        if self.work_years_min is not None and self.work_years_max is not None:
            if self.work_years_max < self.work_years_min:
                raise ValueError('最大工作年限不能小于最小工��年限')
        if self.salary_min is not None and self.salary_max is not None:
            if self.salary_max and self.salary_min and self.salary_max < self.salary_min:
                raise ValueError('最高薪资不能低于最低薪资')
        return self


class JobResponse(BaseModel):
    id: int
    user_id: int = 0
    title: str
    department: str
    education_min: str
    school_tier_min: str = ""
    work_years_min: int
    work_years_max: int
    salary_min: float
    salary_max: float
    required_skills: str
    soft_requirements: str
    greeting_templates: str
    is_active: bool
    created_at: datetime | None = None
    updated_at: datetime | None = None
    jd_text: str = ""
    competency_model: dict | None = None
    competency_model_status: str = "none"
    scoring_weights: dict | None = None
    batch_collect_criteria: dict | None = None
    model_config = {"from_attributes": True}


class JobListResponse(BaseModel):
    total: int
    items: list[JobResponse]


class ScreeningResult(BaseModel):
    resume_id: int
    resume_name: str
    passed: bool
    reject_reasons: list[str] = Field(default_factory=list)


class ScreeningResponse(BaseModel):
    job_id: int
    total: int
    passed: int
    rejected: int
    results: list[ScreeningResult]
