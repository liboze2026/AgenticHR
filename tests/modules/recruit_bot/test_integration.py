"""F3 端到端后端路径集成测试."""
import pytest
from datetime import datetime, timezone


def _mk_user(db, user_id, username, daily_cap=1000):
    from app.modules.auth.models import User
    u = User(id=user_id, username=username, password_hash="x", daily_cap=daily_cap)
    db.add(u); db.commit()


def _mk_job(db, user_id, threshold=30):
    from app.modules.screening.models import Job
    j = Job(
        user_id=user_id, title="后端", jd_text="x",
        competency_model={
            "schema_version": 1,
            "hard_skills": [{"name":"Python","weight":9,"must_have":True}],
            "soft_skills":[],"experience":{"years_min":2,"years_max":5,"industries":[]},
            "education":{"min_level":"本科"},"job_level":"","bonus_items":[],
            "exclusions":[],"assessment_dimensions":[],
            "source_jd_hash":"h","extracted_at":"2026-04-21T00:00:00Z",
        },
        competency_model_status="approved", greet_threshold=threshold,
    )
    db.add(j); db.commit(); db.refresh(j)
    return j


def _mk_cand(boss_id="b1"):
    from app.modules.recruit_bot.schemas import ScrapedCandidate
    return ScrapedCandidate(
        name="张三", boss_id=boss_id, age=28, education="本科",
        school="X 大", major="CS", intended_job="后端",
        work_years=3, skill_tags=["Python", "Redis"],
    )


@pytest.mark.asyncio
async def test_full_pipeline_should_greet_then_record(db):
    from app.modules.recruit_bot.service import (
        evaluate_and_record, record_greet_sent, get_daily_usage,
    )
    from app.modules.resume.models import Resume
    _mk_user(db, 1, "hr1")
    job = _mk_job(db, user_id=1, threshold=30)

    dec = await evaluate_and_record(db, user_id=1, job_id=job.id, candidate=_mk_cand())
    assert dec.decision == "should_greet"
    assert dec.resume_id is not None

    record_greet_sent(db, user_id=1, resume_id=dec.resume_id, success=True)
    r = db.query(Resume).filter_by(id=dec.resume_id).first()
    assert r.greet_status == "greeted"
    assert r.greeted_at is not None

    usage = get_daily_usage(db, user_id=1)
    assert usage.used == 1


@pytest.mark.asyncio
async def test_full_pipeline_rejected(db):
    """高阈值场景 — candidate 无 must-have 技能 → rejected_low_score."""
    from app.modules.recruit_bot.service import evaluate_and_record
    from app.modules.resume.models import Resume
    from app.modules.recruit_bot.schemas import ScrapedCandidate
    _mk_user(db, 1, "hr1")
    job = _mk_job(db, user_id=1, threshold=50)
    # 缺 Python must-have → hard_gate 不通过 → 低分
    c = ScrapedCandidate(
        name="李四", boss_id="reject_target", age=28, education="本科",
        school="X 大", major="CS", intended_job="后端",
        work_years=3, skill_tags=["Redis"],
    )
    dec = await evaluate_and_record(db, user_id=1, job_id=job.id, candidate=c)
    assert dec.decision == "rejected_low_score"
    r = db.query(Resume).filter_by(id=dec.resume_id).first()
    assert r.status == "rejected"
    assert r.greet_status == "none"


@pytest.mark.asyncio
async def test_idempotent_evaluate(db):
    from app.modules.recruit_bot.service import evaluate_and_record
    _mk_user(db, 1, "hr1")
    job = _mk_job(db, user_id=1, threshold=30)
    d1 = await evaluate_and_record(db, user_id=1, job_id=job.id, candidate=_mk_cand())
    d2 = await evaluate_and_record(db, user_id=1, job_id=job.id, candidate=_mk_cand())
    assert d1.resume_id == d2.resume_id
    assert d1.decision == d2.decision


@pytest.mark.asyncio
async def test_idempotent_record_greet_preserves_timestamp(db):
    from app.modules.recruit_bot.service import (
        evaluate_and_record, record_greet_sent,
    )
    from app.modules.resume.models import Resume
    _mk_user(db, 1, "hr1")
    job = _mk_job(db, user_id=1, threshold=30)
    d = await evaluate_and_record(db, user_id=1, job_id=job.id, candidate=_mk_cand())
    record_greet_sent(db, user_id=1, resume_id=d.resume_id, success=True)
    r1 = db.query(Resume).filter_by(id=d.resume_id).first()
    t1 = r1.greeted_at
    record_greet_sent(db, user_id=1, resume_id=d.resume_id, success=True)
    r2 = db.query(Resume).filter_by(id=d.resume_id).first()
    assert r2.greeted_at == t1


@pytest.mark.asyncio
async def test_cap_across_multi_users(db):
    """user_A 打满 cap → 被 blocked, user_B 不受影响."""
    from app.modules.recruit_bot.service import (
        evaluate_and_record, record_greet_sent,
    )
    from app.modules.auth.models import User
    _mk_user(db, 1, "hr1")
    _mk_user(db, 2, "hr2")

    job_a = _mk_job(db, user_id=1, threshold=30)
    job_b = _mk_job(db, user_id=2, threshold=30)

    ua = db.query(User).filter_by(id=1).first(); ua.daily_cap = 1; db.commit()

    d1 = await evaluate_and_record(db, user_id=1, job_id=job_a.id, candidate=_mk_cand(boss_id="x1"))
    record_greet_sent(db, user_id=1, resume_id=d1.resume_id, success=True)

    d2 = await evaluate_and_record(db, user_id=1, job_id=job_a.id, candidate=_mk_cand(boss_id="x2"))
    assert d2.decision == "blocked_daily_cap"

    # user_B 不受影响
    d3 = await evaluate_and_record(db, user_id=2, job_id=job_b.id, candidate=_mk_cand(boss_id="x3"))
    assert d3.decision == "should_greet"
