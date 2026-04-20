from app.modules.matching.scorers.evidence import build_deterministic_evidence


class _FakeResume:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def test_skill_offset_in_skills_field():
    resume = _FakeResume(
        skills="Python, Go, FastAPI",
        work_experience="", project_experience="", work_years=3, education="本科",
    )
    ev = build_deterministic_evidence(
        resume=resume,
        matched_skills=["Python"],
        experience_range=(3, 8),
        matched_industries=[],
    )
    skill_ev = ev["skill"]
    assert len(skill_ev) == 1
    assert skill_ev[0]["source"] == "skills"
    assert skill_ev[0]["text"] == "匹配到 Python"
    start, end = skill_ev[0]["offset"]
    assert resume.skills[start:end].lower() == "python"


def test_skill_falls_back_to_project_experience():
    resume = _FakeResume(
        skills="",
        work_experience="",
        project_experience="用 FastAPI 做过三个后端项目",
        work_years=3, education="本科",
    )
    ev = build_deterministic_evidence(
        resume=resume, matched_skills=["FastAPI"],
        experience_range=(3, 8), matched_industries=[],
    )
    assert ev["skill"][0]["source"] == "project_experience"


def test_experience_evidence_no_offset():
    resume = _FakeResume(skills="", work_experience="", project_experience="",
                         work_years=5, education="本科")
    ev = build_deterministic_evidence(
        resume=resume, matched_skills=[], experience_range=(3, 8),
        matched_industries=[],
    )
    assert ev["experience"][0]["source"] == "work_years"
    assert ev["experience"][0]["offset"] is None
    assert "5" in ev["experience"][0]["text"]


def test_industry_keyword_offset():
    resume = _FakeResume(
        skills="", work_experience="曾在某互联网公司任职 5 年",
        project_experience="", work_years=5, education="本科",
    )
    ev = build_deterministic_evidence(
        resume=resume, matched_skills=[],
        experience_range=(3, 8), matched_industries=["互联网"],
    )
    assert ev["industry"][0]["source"] == "work_experience"
    start, end = ev["industry"][0]["offset"]
    assert resume.work_experience[start:end] == "互联网"


def test_unmatched_skill_not_in_evidence():
    resume = _FakeResume(skills="Python", work_experience="",
                         project_experience="", work_years=3, education="本科")
    ev = build_deterministic_evidence(
        resume=resume, matched_skills=[],
        experience_range=(3, 8), matched_industries=[],
    )
    assert ev["skill"] == []


def test_education_evidence():
    resume = _FakeResume(skills="", work_experience="", project_experience="",
                         work_years=3, education="硕士")
    ev = build_deterministic_evidence(
        resume=resume, matched_skills=[],
        experience_range=(3, 8), matched_industries=[],
    )
    assert ev["education"][0]["source"] == "education"
    assert "硕士" in ev["education"][0]["text"]
