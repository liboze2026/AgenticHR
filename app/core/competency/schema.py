"""F1 能力模型 Pydantic schema."""
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field


class HardSkill(BaseModel):
    name: str
    canonical_id: int | None = None
    level: Literal["了解", "熟练", "精通"] = "熟练"
    weight: int = Field(ge=1, le=10)
    must_have: bool = False


class SoftSkill(BaseModel):
    name: str
    weight: int = Field(ge=1, le=10)
    assessment_stage: Literal["简历", "IM", "面试"] = "面试"


class ExperienceRequirement(BaseModel):
    years_min: int = 0
    years_max: int | None = None
    industries: list[str] = []
    company_scale: str | None = None


class EducationRequirement(BaseModel):
    min_level: Literal["大专", "本科", "硕士", "博士"] = "本科"
    preferred_level: str | None = None
    prestigious_bonus: bool = False


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
