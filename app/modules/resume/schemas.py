"""简历输入/输出数据结构"""
import re
from datetime import datetime
from pydantic import BaseModel, Field, field_validator


class ResumeCreate(BaseModel):
    """创建简历"""
    name: str = Field(..., min_length=1, max_length=100, description="姓名")
    phone: str = Field(default="", max_length=20, description="手机号")
    email: str = Field(default="", max_length=200, description="邮箱")

    @field_validator('phone')
    @classmethod
    def validate_phone(cls, v):
        if v and not re.match(r'^1[3-9]\d{9}$', v):
            raise ValueError('手机号格式不正确，需为11位中国手机号')
        return v

    @field_validator('email')
    @classmethod
    def validate_email(cls, v):
        if v and not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', v):
            raise ValueError('邮箱格式不正确')
        return v
    education: str = Field(default="", max_length=50, description="学历")
    bachelor_school: str = Field(default="", max_length=200, description="本科学校")
    master_school: str = Field(default="", max_length=200, description="硕士学校")
    phd_school: str = Field(default="", max_length=200, description="博士学校")
    work_years: int = Field(default=0, ge=0, description="工作年限")
    expected_salary_min: float = Field(default=0, ge=0, description="期望薪资下限")
    expected_salary_max: float = Field(default=0, ge=0, description="期望薪资上限")
    job_intention: str = Field(default="", max_length=200, description="求职意向")
    skills: str = Field(default="", description="技能标签，逗号分隔")
    work_experience: str = Field(default="", description="工作经历")
    project_experience: str = Field(default="", description="项目经历")
    self_evaluation: str = Field(default="", description="自我评价")
    source: str = Field(default="manual", description="来源: boss_zhipin, email, manual")
    boss_id: str = Field(default="", description="Boss 直聘候选人 ID")
    raw_text: str = Field(default="", description="简历原始文本")
    pdf_path: str = Field(default="", description="PDF 文件路径")


class ResumeUpdate(BaseModel):
    """更新简历（全部字段可选，支持逐字段编辑）"""
    name: str | None = Field(None, max_length=100)
    phone: str | None = Field(None, max_length=20)
    email: str | None = Field(None, max_length=200)

    @field_validator('phone')
    @classmethod
    def validate_phone(cls, v):
        if v and not re.match(r'^1[3-9]\d{9}$', v):
            raise ValueError('手机号格式不正确，需为11位中国手机号')
        return v

    @field_validator('email')
    @classmethod
    def validate_email(cls, v):
        if v and not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', v):
            raise ValueError('邮箱格式不正确')
        return v
    education: str | None = Field(None, max_length=50)
    bachelor_school: str | None = Field(None, max_length=200)
    master_school: str | None = Field(None, max_length=200)
    phd_school: str | None = Field(None, max_length=200)
    work_years: int | None = Field(None, ge=0)
    job_intention: str | None = Field(None, max_length=200)
    skills: str | None = None
    work_experience: str | None = None
    project_experience: str | None = None
    self_evaluation: str | None = None
    status: str | None = Field(None, description="pending, passed, rejected")
    reject_reason: str | None = None


class ResumeResponse(BaseModel):
    """简历详情响应"""
    id: int
    name: str
    phone: str
    email: str
    education: str
    bachelor_school: str
    master_school: str
    phd_school: str
    qr_code_path: str
    work_years: int
    expected_salary_min: float
    expected_salary_max: float
    job_intention: str
    skills: str
    work_experience: str
    project_experience: str
    self_evaluation: str
    source: str
    raw_text: str
    pdf_path: str
    status: str
    ai_parsed: str
    ai_score: float | None
    ai_summary: str
    reject_reason: str
    seniority: str = ""
    intake_status: str | None = None
    boss_id: str = ""
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ResumeListResponse(BaseModel):
    """简历列表响应（分页）"""
    total: int
    page: int
    page_size: int
    items: list[ResumeResponse]
