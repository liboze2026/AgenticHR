import time
from unittest.mock import patch, AsyncMock
from app.modules.resume.models import Resume
from app.modules.screening.models import Job
from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.im_intake.models import IntakeSlot
from app.modules.im_intake.templates import HARD_SLOT_KEYS


def _seed_complete_candidate_with_resume(
    session,
    user_id=1,
    boss_id="b1",
    name="R0",
    education="本科",
    school_tier="985",
):
    """建一条硬筛通过的候选人 (四齐全 + 已 promote → Resume).

    硬筛规则: 三个 hard_slot 全填 + pdf_path 非空 + 学历/院校等级符合 job 门槛.
    Resume 也要 ai_parsed='yes' 才能进入 F2 评分.
    """
    cand = IntakeCandidate(
        user_id=user_id, boss_id=boss_id, name=name,
        pdf_path=f"data/{boss_id}.pdf", intake_status="complete",
        education=education, school_tier=school_tier,
        source="manual",
    )
    session.add(cand)
    session.commit()
    session.refresh(cand)
    for key in HARD_SLOT_KEYS:
        session.add(IntakeSlot(
            candidate_id=cand.id, slot_key=key, slot_category="hard",
            value="filled", ask_count=1,
        ))
    resume = Resume(
        name=name, phone="", skills="Python", work_years=2,
        education=education, ai_parsed="yes", source="manual",
        seniority="中级", user_id=user_id, boss_id=boss_id,
        intake_candidate_id=cand.id,
    )
    session.add(resume)
    session.commit()
    cand.promoted_resume_id = resume.id
    session.commit()
    return cand, resume


def _seed(session, n_resumes=3, with_hard_filter_pass=True):
    cm = {"hard_skills": [], "experience": {"years_min": 0},
          "education": {}, "job_level": "中级"}
    job = Job(title="后端", is_active=True, required_skills="",
              competency_model=cm, competency_model_status="approved",
              user_id=1, education_min="", school_tier_min="")
    session.add(job); session.commit()

    if with_hard_filter_pass:
        for i in range(n_resumes):
            _seed_complete_candidate_with_resume(
                session, boss_id=f"b{i}", name=f"R{i}",
            )
    else:
        for i in range(n_resumes):
            r = Resume(name=f"R{i}", phone="", skills="Python", work_years=2,
                       education="本科", ai_parsed="yes", source="manual",
                       seniority="中级", user_id=1)
            session.add(r); session.commit()
    return job


def test_recompute_job_returns_task_id(client, db_session):
    job = _seed(db_session, n_resumes=2)
    with patch("app.modules.matching.service.enhance_evidence_with_llm",
               new=AsyncMock(side_effect=lambda ev, *a, **kw: ev)):
        resp = client.post("/api/matching/recompute", json={"job_id": job.id})
    assert resp.status_code == 200
    data = resp.json()
    assert "task_id" in data
    # total = 硬筛通过的 Resume 数 (2 candidate 全过, 因 job 无门槛)
    assert data["total"] == 2


def test_recompute_status_endpoint(client, db_session):
    job = _seed(db_session, n_resumes=1)
    with patch("app.modules.matching.service.enhance_evidence_with_llm",
               new=AsyncMock(side_effect=lambda ev, *a, **kw: ev)):
        resp = client.post("/api/matching/recompute", json={"job_id": job.id})
    task_id = resp.json()["task_id"]

    # Wait briefly for background task
    time.sleep(0.1)
    status_resp = client.get(f"/api/matching/recompute/status/{task_id}")
    assert status_resp.status_code == 200
    s = status_resp.json()
    assert s["task_id"] == task_id
    assert s["total"] == 1


def test_recompute_validates_one_of(client):
    resp = client.post("/api/matching/recompute", json={})
    assert resp.status_code == 400


def test_recompute_skips_resumes_failing_hard_filter(client, db_session):
    """硬筛串联: 学历不达标的 candidate 不应进入 F2."""
    cm = {"hard_skills": [], "experience": {"years_min": 0},
          "education": {}, "job_level": "中级"}
    job = Job(title="后端", is_active=True, required_skills="",
              competency_model=cm, competency_model_status="approved",
              user_id=1, education_min="硕士", school_tier_min="")
    db_session.add(job); db_session.commit()

    _seed_complete_candidate_with_resume(
        db_session, boss_id="ok", name="硕士candidate", education="硕士",
    )
    _seed_complete_candidate_with_resume(
        db_session, boss_id="fail", name="本科candidate", education="本科",
    )

    with patch("app.modules.matching.service.enhance_evidence_with_llm",
               new=AsyncMock(side_effect=lambda ev, *a, **kw: ev)):
        resp = client.post("/api/matching/recompute", json={"job_id": job.id})
    assert resp.status_code == 200
    # 仅硕士 candidate 通过硬筛, total = 1
    assert resp.json()["total"] == 1


def test_recompute_zero_when_no_candidate_passes_hard_filter(client, db_session):
    """硬筛串联: 无候选人通过门槛时 total = 0, 任务也启动 (空跑即结束)."""
    cm = {"hard_skills": [], "experience": {"years_min": 0},
          "education": {}, "job_level": "中级"}
    job = Job(title="后端", is_active=True, required_skills="",
              competency_model=cm, competency_model_status="approved",
              user_id=1, education_min="博士", school_tier_min="")
    db_session.add(job); db_session.commit()

    _seed_complete_candidate_with_resume(
        db_session, boss_id="b1", education="本科",
    )
    with patch("app.modules.matching.service.enhance_evidence_with_llm",
               new=AsyncMock(side_effect=lambda ev, *a, **kw: ev)):
        resp = client.post("/api/matching/recompute", json={"job_id": job.id})
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


def test_recompute_purges_stale_matching_results(client, db_session):
    """再次分析: 硬筛失败的人之前留在 matching_results 的旧行必须删."""
    from app.modules.matching.models import MatchingResult
    from datetime import datetime, timezone

    cm = {"hard_skills": [], "experience": {"years_min": 0},
          "education": {}, "job_level": "中级"}
    job = Job(title="后端", is_active=True, required_skills="",
              competency_model=cm, competency_model_status="approved",
              user_id=1, education_min="硕士")  # 仅硕士过硬筛
    db_session.add(job); db_session.commit()

    # 一个硕士过硬筛的人, 一个本科不过硬筛的人
    _, r_pass = _seed_complete_candidate_with_resume(
        db_session, boss_id="ok", name="硕士", education="硕士",
    )
    _, r_fail = _seed_complete_candidate_with_resume(
        db_session, boss_id="fail", name="本科", education="本科",
    )

    # 模拟历史遗留: 两人都已有 matching_results 行 (上次硬筛规则不同)
    now = datetime.now(timezone.utc)
    for rid in (r_pass.id, r_fail.id):
        db_session.add(MatchingResult(
            resume_id=rid, job_id=job.id,
            total_score=50.0, skill_score=50, experience_score=50,
            seniority_score=50, education_score=50, industry_score=50,
            hard_gate_passed=1, missing_must_haves="[]",
            evidence="{}", tags="[]",
            competency_hash="old", weights_hash="old",
            scored_at=now,
        ))
    db_session.commit()
    assert db_session.query(MatchingResult).filter_by(job_id=job.id).count() == 2

    with patch("app.modules.matching.service.enhance_evidence_with_llm",
               new=AsyncMock(side_effect=lambda ev, *a, **kw: ev)):
        resp = client.post("/api/matching/recompute", json={"job_id": job.id})
    assert resp.status_code == 200

    # 本科那行应被清理, 仅硕士保留
    rows = db_session.query(MatchingResult).filter_by(job_id=job.id).all()
    surviving_ids = {row.resume_id for row in rows}
    assert r_fail.id not in surviving_ids
    assert r_pass.id in surviving_ids


def test_recompute_purges_all_when_zero_pass_hard_filter(client, db_session):
    """硬筛 0 通过时, 本 job 全部 matching_results 行清空 (列表也归零)."""
    from app.modules.matching.models import MatchingResult
    from datetime import datetime, timezone

    cm = {"hard_skills": [], "experience": {"years_min": 0},
          "education": {}, "job_level": "中级"}
    job = Job(title="后端", is_active=True, required_skills="",
              competency_model=cm, competency_model_status="approved",
              user_id=1, education_min="博士")
    db_session.add(job); db_session.commit()

    _, r_fail = _seed_complete_candidate_with_resume(
        db_session, boss_id="b1", education="本科",
    )
    db_session.add(MatchingResult(
        resume_id=r_fail.id, job_id=job.id,
        total_score=50.0, skill_score=50, experience_score=50,
        seniority_score=50, education_score=50, industry_score=50,
        hard_gate_passed=1, missing_must_haves="[]",
        evidence="{}", tags="[]",
        competency_hash="old", weights_hash="old",
        scored_at=datetime.now(timezone.utc),
    ))
    db_session.commit()

    with patch("app.modules.matching.service.enhance_evidence_with_llm",
               new=AsyncMock(side_effect=lambda ev, *a, **kw: ev)):
        resp = client.post("/api/matching/recompute", json={"job_id": job.id})
    assert resp.status_code == 200
    assert resp.json()["total"] == 0
    assert db_session.query(MatchingResult).filter_by(job_id=job.id).count() == 0


def test_recompute_resume_path_unaffected_by_hard_filter(client, db_session):
    """硬筛串联只在 job_id 路径生效, resume_id 路径行为不变."""
    cm = {"hard_skills": [], "experience": {"years_min": 0},
          "education": {}, "job_level": "中级"}
    job = Job(title="后端", is_active=True, required_skills="",
              competency_model=cm, competency_model_status="approved",
              user_id=1, education_min="博士")
    db_session.add(job); db_session.commit()

    cand, resume = _seed_complete_candidate_with_resume(
        db_session, boss_id="b1", education="本科",
    )
    with patch("app.modules.matching.service.enhance_evidence_with_llm",
               new=AsyncMock(side_effect=lambda ev, *a, **kw: ev)):
        resp = client.post(
            "/api/matching/recompute", json={"resume_id": resume.id},
        )
    assert resp.status_code == 200
    # resume_id 路径以 approved+is_active job 数为 total
    assert resp.json()["total"] == 1
