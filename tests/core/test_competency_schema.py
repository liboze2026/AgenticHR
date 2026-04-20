"""core.competency.schema — CompetencyModel Pydantic."""
import pytest
from datetime import datetime
from pydantic import ValidationError

from app.core.competency.schema import (
    HardSkill, SoftSkill, ExperienceRequirement,
    EducationRequirement, AssessmentDimension, CompetencyModel,
)


def test_hard_skill_defaults():
    s = HardSkill(name="Python", weight=8)
    assert s.level == "熟练"
    assert s.must_have is False
    assert s.canonical_id is None


def test_hard_skill_weight_range():
    with pytest.raises(ValidationError):
        HardSkill(name="x", weight=0)
    with pytest.raises(ValidationError):
        HardSkill(name="x", weight=11)
    HardSkill(name="x", weight=1)
    HardSkill(name="x", weight=10)


def test_hard_skill_level_normalization():
    # 未知值降级为默认值"熟练"，不再抛异常
    s = HardSkill(name="x", weight=5, level="大师")
    assert s.level == "熟练"
    # 近义词映射
    assert HardSkill(name="x", weight=5, level="熟悉").level == "熟练"
    assert HardSkill(name="x", weight=5, level="了解").level == "了解"
    assert HardSkill(name="x", weight=5, level="精通").level == "精通"


def test_soft_skill_stage_normalization():
    # 未知值降级为"面试"
    s = SoftSkill(name="沟通", weight=5, assessment_stage="随便")
    assert s.assessment_stage == "面试"
    assert SoftSkill(name="沟通", weight=5, assessment_stage="简历").assessment_stage == "简历"


def test_education_level_normalization():
    # 未知值降级为"本科"
    e = EducationRequirement(min_level="专科以下")
    assert e.min_level == "本科"
    assert EducationRequirement(min_level="专科").min_level == "大专"
    assert EducationRequirement(min_level="本科").min_level == "本科"


def test_experience_years_optional_max():
    e = ExperienceRequirement(years_min=3)
    assert e.years_max is None
    assert e.industries == []


def test_competency_model_full():
    m = CompetencyModel(
        hard_skills=[HardSkill(name="Python", weight=9)],
        soft_skills=[SoftSkill(name="沟通", weight=6)],
        experience=ExperienceRequirement(years_min=3, years_max=7),
        education=EducationRequirement(min_level="本科"),
        source_jd_hash="abc123",
        extracted_at=datetime.utcnow(),
    )
    assert m.schema_version == 1
    assert m.hard_skills[0].name == "Python"


def test_competency_model_minimal_required():
    m = CompetencyModel(
        hard_skills=[],
        source_jd_hash="h",
        extracted_at=datetime.utcnow(),
    )
    assert m.soft_skills == []
    assert m.education.min_level == "本科"


def test_competency_model_json_roundtrip():
    m = CompetencyModel(
        hard_skills=[HardSkill(name="Go", weight=7, must_have=True)],
        source_jd_hash="h",
        extracted_at=datetime(2026, 4, 20, 10, 0, 0),
    )
    j = m.model_dump_json()
    m2 = CompetencyModel.model_validate_json(j)
    assert m2.hard_skills[0].name == "Go"
    assert m2.hard_skills[0].must_have is True
