"""recruit_bot Pydantic schemas 校验."""
import pytest
from pydantic import ValidationError


def test_scraped_candidate_minimal():
    from app.modules.recruit_bot.schemas import ScrapedCandidate
    c = ScrapedCandidate(name="张三", boss_id="abc123")
    assert c.name == "张三"
    assert c.boss_id == "abc123"
    assert c.age is None
    assert c.skill_tags == []


def test_scraped_candidate_requires_boss_id():
    from app.modules.recruit_bot.schemas import ScrapedCandidate
    with pytest.raises(ValidationError):
        ScrapedCandidate(name="张三", boss_id="")


def test_scraped_candidate_full():
    from app.modules.recruit_bot.schemas import ScrapedCandidate
    c = ScrapedCandidate(
        name="李四", boss_id="xyz",
        age=28, education="硕士", grad_year=2027, work_years=3,
        school="清华", major="CS", intended_job="后端工程师",
        skill_tags=["Python", "Redis"],
        school_tier_tags=["985院校"],
        ranking_tags=["专业前10%"],
        expected_salary="30-40K", active_status="刚刚活跃",
        recommendation_reason="来自相似职位Python",
        latest_work_brief="2022.01 - 2024.12 字节 · 后端",
        raw_text="...", boss_current_job_title="全栈工程师",
    )
    assert c.work_years == 3
    assert "Python" in c.skill_tags


def test_recruit_decision_literal():
    from app.modules.recruit_bot.schemas import RecruitDecision
    d = RecruitDecision(decision="should_greet", resume_id=1, score=75, threshold=60)
    assert d.decision == "should_greet"


def test_recruit_decision_invalid():
    from app.modules.recruit_bot.schemas import RecruitDecision
    with pytest.raises(ValidationError):
        RecruitDecision(decision="invalid_state")


def test_usage_info_shape():
    from app.modules.recruit_bot.schemas import UsageInfo
    u = UsageInfo(used=10, cap=1000, remaining=990)
    assert u.remaining == 990


def test_greet_record_request():
    from app.modules.recruit_bot.schemas import GreetRecordRequest
    r = GreetRecordRequest(resume_id=1, success=True)
    assert r.error_msg == ""
    r2 = GreetRecordRequest(resume_id=2, success=False, error_msg="button_not_found")
    assert r2.error_msg == "button_not_found"
