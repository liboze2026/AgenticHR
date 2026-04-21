"""evaluate_and_record — 核心决策."""
import pytest


def _mk_job(db, user_id=1, threshold=60, with_competency=True):
    from app.modules.screening.models import Job
    comp = {
        "schema_version": 1,
        "hard_skills": [
            {"name": "Python", "weight": 9, "must_have": True},
            {"name": "Redis", "weight": 5, "must_have": False},
        ],
        "soft_skills": [],
        "experience": {"years_min": 2, "years_max": 5, "industries": []},
        "education": {"min_level": "本科"},
        "job_level": "",
        "bonus_items": [], "exclusions": [], "assessment_dimensions": [],
        "source_jd_hash": "h", "extracted_at": "2026-04-21T00:00:00Z",
    } if with_competency else None
    j = Job(
        user_id=user_id, title="后端", jd_text="招 Python",
        competency_model=comp,
        competency_model_status="approved" if with_competency else "none",
        greet_threshold=threshold,
    )
    db.add(j); db.commit(); db.refresh(j)
    return j


def _mk_candidate(boss_id="b1", name="张三", skills=None, work_years=3, education="本科"):
    from app.modules.recruit_bot.schemas import ScrapedCandidate
    return ScrapedCandidate(
        name=name, boss_id=boss_id, age=28,
        education=education, school="XX 大学", major="CS",
        intended_job="后端", work_years=work_years,
        skill_tags=skills or ["Python", "Redis"],
    )


def _mk_user(db, user_id=1, daily_cap=1000):
    from app.modules.auth.models import User
    u = User(id=user_id, username=f"hr{user_id}", password_hash="x", daily_cap=daily_cap)
    db.add(u); db.commit()
    return u


@pytest.mark.asyncio
async def test_evaluate_should_greet_high_score(db):
    from app.modules.recruit_bot.service import evaluate_and_record
    _mk_user(db)
    job = _mk_job(db, threshold=30)
    c = _mk_candidate()
    dec = await evaluate_and_record(db, user_id=1, job_id=job.id, candidate=c)
    assert dec.decision == "should_greet"
    assert dec.resume_id is not None
    assert dec.score is not None
    assert dec.score >= 30


@pytest.mark.asyncio
async def test_evaluate_rejected_low_score(db):
    """Candidate missing must_have 'Python' → hard gate fails → total ≤ 29 → rejected at threshold 50."""
    from app.modules.recruit_bot.service import evaluate_and_record
    from app.modules.resume.models import Resume
    _mk_user(db)
    job = _mk_job(db, threshold=50)
    # 只留 Redis, 没有 Python (must_have) → 硬门槛失败 → total ≤ 29
    c = _mk_candidate(skills=["Redis"])
    dec = await evaluate_and_record(db, user_id=1, job_id=job.id, candidate=c)
    assert dec.decision == "rejected_low_score"
    r = db.query(Resume).filter_by(id=dec.resume_id).first()
    assert r.status == "rejected"
    assert str(dec.score) in r.reject_reason


@pytest.mark.asyncio
async def test_evaluate_skipped_already_greeted(db):
    from app.modules.recruit_bot.service import evaluate_and_record, upsert_resume_by_boss_id
    _mk_user(db)
    job = _mk_job(db, threshold=30)
    c = _mk_candidate()
    r = upsert_resume_by_boss_id(db, user_id=1, candidate=c)
    r.greet_status = "greeted"
    db.commit()
    dec = await evaluate_and_record(db, user_id=1, job_id=job.id, candidate=c)
    assert dec.decision == "skipped_already_greeted"
    assert dec.resume_id == r.id


@pytest.mark.asyncio
async def test_evaluate_blocked_daily_cap(db):
    """cap=1 且已打过 1 次 → 返 blocked_daily_cap."""
    from app.modules.recruit_bot.service import evaluate_and_record
    from app.modules.resume.models import Resume
    from datetime import datetime, timezone
    _mk_user(db, daily_cap=1)
    prev = Resume(
        user_id=1, name="prev", boss_id="other",
        greet_status="greeted",
        greeted_at=datetime.now(timezone.utc),
        source="boss_zhipin",
    )
    db.add(prev); db.commit()

    job = _mk_job(db, threshold=30)
    c = _mk_candidate(boss_id="new_cand")
    dec = await evaluate_and_record(db, user_id=1, job_id=job.id, candidate=c)
    assert dec.decision == "blocked_daily_cap"


@pytest.mark.asyncio
async def test_evaluate_error_no_competency(db):
    from app.modules.recruit_bot.service import evaluate_and_record
    _mk_user(db)
    job = _mk_job(db, with_competency=False)
    c = _mk_candidate()
    dec = await evaluate_and_record(db, user_id=1, job_id=job.id, candidate=c)
    assert dec.decision == "error_no_competency"


@pytest.mark.asyncio
async def test_evaluate_writes_audit_events(db):
    from app.modules.recruit_bot.service import evaluate_and_record
    from app.core.audit.models import AuditEvent
    _mk_user(db)
    job = _mk_job(db, threshold=30)
    c = _mk_candidate()
    await evaluate_and_record(db, user_id=1, job_id=job.id, candidate=c)
    events = db.query(AuditEvent).filter(AuditEvent.f_stage == "F3_evaluate").all()
    assert len(events) >= 1


@pytest.mark.asyncio
async def test_evaluate_foreign_job_raises(db):
    from app.modules.recruit_bot.service import evaluate_and_record
    _mk_user(db, user_id=1)
    _mk_user(db, user_id=999)
    job = _mk_job(db, user_id=999)
    c = _mk_candidate()
    with pytest.raises(ValueError, match="not found"):
        await evaluate_and_record(db, user_id=1, job_id=job.id, candidate=c)
