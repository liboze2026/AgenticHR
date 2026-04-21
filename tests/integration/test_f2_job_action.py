"""F2 per-(resume, job) action 测试.

测试 PATCH /api/matching/results/{id}/action 和
GET /api/matching/passed-resumes/{job_id} 端点。
"""
import pytest
from datetime import datetime, timezone

from app.modules.matching.models import MatchingResult
from app.modules.resume.models import Resume
from app.modules.screening.models import Job


def _mk_resume(session, **kw):
    defaults = dict(
        name="候选人A", phone="13800000001", skills="Python",
        work_years=3, education="本科", seniority="中级",
        ai_parsed="yes", source="manual",
    )
    defaults.update(kw)
    r = Resume(**defaults)
    session.add(r)
    session.commit()
    return r


def _mk_job(session, **kw):
    defaults = dict(
        title="工程师岗位", is_active=True, required_skills="",
        competency_model={
            "hard_skills": [],
            "experience": {"years_min": 0},
            "education": {},
            "job_level": "中级",
        },
        competency_model_status="approved",
    )
    defaults.update(kw)
    j = Job(**defaults)
    session.add(j)
    session.commit()
    return j


def _mk_result(session, resume_id, job_id, **kw):
    defaults = dict(
        resume_id=resume_id, job_id=job_id,
        total_score=75.0, skill_score=75.0,
        experience_score=80.0, seniority_score=80.0,
        education_score=80.0, industry_score=80.0,
        hard_gate_passed=1, missing_must_haves="[]",
        evidence="{}", tags='["高匹配"]',
        competency_hash="hash_c", weights_hash="hash_w",
        scored_at=datetime.now(timezone.utc),
    )
    defaults.update(kw)
    row = MatchingResult(**defaults)
    session.add(row)
    session.commit()
    return row


# ── PATCH action tests ──────────────────────────────────────────────────────

def test_set_action_passed(client, db_session):
    """PATCH passed → job_action='passed'; GET results 中也能看到。"""
    resume = _mk_resume(db_session)
    job = _mk_job(db_session)
    result = _mk_result(db_session, resume.id, job.id)
    assert result.job_action is None

    resp = client.patch(f"/api/matching/results/{result.id}/action", json={"action": "passed"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == result.id
    assert data["job_action"] == "passed"

    # GET results 应包含 job_action
    resp2 = client.get(f"/api/matching/results?job_id={job.id}")
    assert resp2.status_code == 200
    items = resp2.json()["items"]
    assert len(items) == 1
    assert items[0]["job_action"] == "passed"


def test_set_action_rejected(client, db_session):
    """PATCH rejected → job_action='rejected'。"""
    resume = _mk_resume(db_session, name="候选人B")
    job = _mk_job(db_session, title="另一岗位")
    result = _mk_result(db_session, resume.id, job.id)

    resp = client.patch(f"/api/matching/results/{result.id}/action", json={"action": "rejected"})
    assert resp.status_code == 200
    assert resp.json()["job_action"] == "rejected"


def test_set_action_clear_to_null(client, db_session):
    """先设为 passed，再 PATCH null → job_action 清空。"""
    resume = _mk_resume(db_session, name="候选人C")
    job = _mk_job(db_session, title="清空测试岗位")
    result = _mk_result(db_session, resume.id, job.id, job_action="passed")

    resp = client.patch(f"/api/matching/results/{result.id}/action", json={"action": None})
    assert resp.status_code == 200
    assert resp.json()["job_action"] is None

    # GET results 也应看到 null
    resp2 = client.get(f"/api/matching/results?job_id={job.id}")
    assert resp2.json()["items"][0]["job_action"] is None


def test_set_action_invalid_value_returns_400(client, db_session):
    """非法 action 值 → 400 Bad Request。"""
    resume = _mk_resume(db_session, name="候选人D")
    job = _mk_job(db_session, title="无效值测试岗位")
    result = _mk_result(db_session, resume.id, job.id)

    resp = client.patch(f"/api/matching/results/{result.id}/action", json={"action": "approved"})
    assert resp.status_code == 400


def test_set_action_nonexistent_result_returns_404(client, db_session):
    """不存在的 result_id → 404。"""
    resp = client.patch("/api/matching/results/999999/action", json={"action": "passed"})
    assert resp.status_code == 404


def test_set_action_scoped_to_job(client, db_session):
    """一个简历在岗位A标记 passed 不影响岗位B的 job_action。"""
    resume = _mk_resume(db_session, name="跨岗位候选人")
    job_a = _mk_job(db_session, title="岗位A")
    job_b = _mk_job(db_session, title="岗位B")
    result_a = _mk_result(db_session, resume.id, job_a.id)
    result_b = _mk_result(db_session, resume.id, job_b.id)

    # 只标记岗位A
    client.patch(f"/api/matching/results/{result_a.id}/action", json={"action": "passed"})

    # 岗位A的结果应为 passed
    resp_a = client.get(f"/api/matching/results?job_id={job_a.id}")
    assert resp_a.json()["items"][0]["job_action"] == "passed"

    # 岗位B的结果应仍为 null
    resp_b = client.get(f"/api/matching/results?job_id={job_b.id}")
    assert resp_b.json()["items"][0]["job_action"] is None


# ── GET passed-resumes tests ─────────────────────────────────────────────────

def test_list_passed_for_job_returns_only_passed(client, db_session):
    """GET /passed-resumes/{job_id} 只返回 job_action='passed' 的候选人。"""
    resume_pass = _mk_resume(db_session, name="通过候选人", phone="13800000002")
    resume_rej = _mk_resume(db_session, name="淘汰候选人", phone="13800000003")
    resume_null = _mk_resume(db_session, name="未评估候选人", phone="13800000004")
    job = _mk_job(db_session, title="只看通过岗位")

    _mk_result(db_session, resume_pass.id, job.id, job_action="passed")
    _mk_result(db_session, resume_rej.id, job.id, job_action="rejected")
    _mk_result(db_session, resume_null.id, job.id)  # job_action=None

    resp = client.get(f"/api/matching/passed-resumes/{job.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["name"] == "通过候选人"
    assert data[0]["phone"] == "13800000002"


def test_list_passed_for_job_empty_when_none(client, db_session):
    """该岗位无任何 passed 记录 → 返回空列表。"""
    job = _mk_job(db_session, title="空岗位")
    resp = client.get(f"/api/matching/passed-resumes/{job.id}")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_passed_for_job_includes_email(client, db_session):
    """返回结果包含 email 字段。"""
    resume = _mk_resume(db_session, name="有邮箱候选人", phone="13800000005")
    resume.email = "test@example.com"
    db_session.commit()
    job = _mk_job(db_session, title="邮箱测试岗位")
    _mk_result(db_session, resume.id, job.id, job_action="passed")

    resp = client.get(f"/api/matching/passed-resumes/{job.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["email"] == "test@example.com"


# ── job_action persists across score (UPSERT) ────────────────────────────────

def test_job_action_preserved_after_upsert(db_session):
    """手动验证：UPSERT 时不覆盖 job_action 字段（service.score_pair 不写 job_action）。"""
    resume = _mk_resume(db_session, name="UPSERT候选人")
    job = _mk_job(db_session, title="UPSERT岗位")
    result = _mk_result(db_session, resume.id, job.id, job_action="passed")

    # 模拟 UPSERT：只修改分数，不触碰 job_action
    result.total_score = 99.0
    db_session.commit()
    db_session.refresh(result)

    assert result.job_action == "passed", "UPSERT 后 job_action 不应被清除"
