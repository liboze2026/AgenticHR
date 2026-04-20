"""F1 能力模型 Pydantic schema."""
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field, field_validator


# LLM 常见近义词映射到标准值
_LEVEL_MAP = {
    "了解": "了解", "基础": "了解", "初级": "了解", "入门": "了解",
    "熟悉": "熟练", "熟练": "熟练", "中级": "熟练", "使用过": "熟练", "通用": "熟练",
    "精通": "精通", "专家": "精通", "高级": "精通", "资深": "精通",
}

_STAGE_MAP = {
    "简历": "简历", "resume": "简历",
    "IM": "IM", "im": "IM", "即时通讯": "IM", "初筛": "IM",
    "面试": "面试", "interview": "面试",
}

_EDU_MAP = {
    "大专": "大专", "专科": "大专",
    "本科": "本科", "学士": "本科",
    "硕士": "硕士", "研究生": "硕士",
    "博士": "博士", "PhD": "博士",
}


class HardSkill(BaseModel):
    name: str
    canonical_id: int | None = None
    level: Literal["了解", "熟练", "精通"] = "熟练"
    weight: int = Field(ge=1, le=10, default=5)
    must_have: bool = False

    @field_validator("level", mode="before")
    @classmethod
    def normalize_level(cls, v):
        if isinstance(v, str):
            mapped = _LEVEL_MAP.get(v.strip())
            if mapped:
                return mapped
            # 包含关键词的模糊匹配
            v_lower = v.strip().lower()
            if any(k in v_lower for k in ("精通", "专家", "高级", "资深")):
                return "精通"
            if any(k in v_lower for k in ("熟悉", "熟练", "使用", "通用", "中级")):
                return "熟练"
        return "熟练"  # 无法识别时默认熟练


class SoftSkill(BaseModel):
    name: str
    weight: int = Field(ge=1, le=10, default=5)
    assessment_stage: Literal["简历", "IM", "面试"] = "面试"

    @field_validator("assessment_stage", mode="before")
    @classmethod
    def normalize_stage(cls, v):
        if isinstance(v, str):
            return _STAGE_MAP.get(v.strip(), "面试")
        return "面试"


class ExperienceRequirement(BaseModel):
    years_min: int = 0
    years_max: int | None = None
    industries: list[str] = []
    company_scale: str | None = None

    @field_validator("years_min", mode="before")
    @classmethod
    def coerce_years_min(cls, v):
        if v is None:
            return 0
        try:
            return int(v)
        except (TypeError, ValueError):
            return 0

    @field_validator("years_max", mode="before")
    @classmethod
    def coerce_years_max(cls, v):
        if v is None:
            return None
        try:
            return int(v)
        except (TypeError, ValueError):
            return None


class EducationRequirement(BaseModel):
    min_level: Literal["大专", "本科", "硕士", "博士"] = "本科"
    preferred_level: str | None = None
    prestigious_bonus: bool = False

    @field_validator("min_level", mode="before")
    @classmethod
    def normalize_edu(cls, v):
        if isinstance(v, str):
            return _EDU_MAP.get(v.strip(), "本科")
        return "本科"


class AssessmentDimension(BaseModel):
    name: str
    description: str = ""
    question_types: list[str] = []


class CompetencyModel(BaseModel):
    schema_version: int = 1
    hard_skills: list[HardSkill]
    soft_skills: list[SoftSkill] = []
    experience: ExperienceRequirement = ExperienceRequirement()
    education: EducationRequirement = EducationRequirement()
    job_level: str = ""
    bonus_items: list[str] = []
    exclusions: list[str] = []
    assessment_dimensions: list[AssessmentDimension] = []
    source_jd_hash: str
    extracted_at: datetime
    reviewed_by: int | None = None
    reviewed_at: datetime | None = None
