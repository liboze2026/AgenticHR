"""F2 per-job scoring weights integration tests.

Covers:
- No custom weights → effective_weights == global
- SET custom weights via PUT → effective_weights == custom
- DELETE → reverts to global
- PUT with sum != 100 → 422
- Two jobs with different weights → score_pair uses each job's own weights
- weights_hash on matching_results reflects effective weights, not global
- Setting custom weights on Job A does NOT affect Job B's results (no spurious staleness)
"""
import json
import pytest
from unittest.mock import patch, AsyncMock

from app.modules.matching.hashing import compute_weights_hash
from app.modules.matching.models import MatchingResult
from app.modules.matching.service import MatchingService
from app.modules.matching.weights import get_effective_weights, _DEFAULT
from app.modules.resume.models import Resume
from app.modules.screening.models import Job


# ── helpers ───────────────────────────────────────────────────────────────────

NO_LLM = patch(
    "app.modules.matching.service.enhance_evidence_with_llm",
    new=AsyncMock(side_effect=lambda ev, *a, **kw: ev),
)

_CM = {
    "hard_skills": [],
    "experience": {"years_min": 3, "years_max": 8},
    "education": {"min_level": "本科"},
    "job_level": "高级",
}


def _mk_resume(session, **kw):
    defaults = dict(
        name="候选人", phone="", skills="Python",
        work_years=5, education="本科", seniority="高级",
        ai_parsed="yes", source="manual",
    )
    defaults.update(kw)
    r = Resume(**defaults)
    session.add(r)
    session.commit()
    return r


def _mk_job(session, scoring_weights=None, user_id=1, **kw):
    defaults = dict(
        title="岗位", is_active=True, required_skills="",
        competency_model=_CM,
        competency_model_status="approved",
        user_id=user_id,
        scoring_weights=scoring_weights,
    )
    defaults.update(kw)
    j = Job(**defaults)
    session.add(j)
    session.commit()
    return j


@pytest.fixture(autouse=True)
def _clean_global_weights():
    """Remove any custom global weights file so tests start with defaults."""
    from app.core.settings.router import _CONFIG_PATH
    existed = _CONFIG_PATH.exists()
    original = _CONFIG_PATH.read_text(encoding="utf-8") if existed else None
    yield
    if original is not None:
        _CONFIG_PATH.write_text(original, encoding="utf-8")
    elif _CONFIG_PATH.exists():
        _CONFIG_PATH.unlink()


# ── unit: get_effective_weights ───────────────────────────────────────────────

def test_no_custom_weights_falls_back_to_global():
    """Job with scoring_weights=None → effective == global/default."""
    job = Job(scoring_weights=None)
    w = get_effective_weights(job)
    assert set(w.keys()) == set(_DEFAULT.keys())
    assert sum(w.values()) > 0  # non-zero


def test_custom_weights_on_job_take_priority():
    """Job with scoring_weights dict → that dict is returned (normalized)."""
    custom = {"skill_match": 50, "experience": 20, "seniority": 10, "education": 10, "industry": 10}
    job = Job(scoring_weights=custom)
    w = get_effective_weights(job)
    assert w["skill_match"] == 50
    assert w["experience"] == 20


def test_get_effective_weights_with_none_job():
    """Passing job=None should return global/default without error."""
    w = get_effective_weights(None)
    assert set(w.keys()) == set(_DEFAULT.keys())


# ── API: GET /scoring-weights ─────────────────────────────────────────────────

def test_get_job_weights_returns_global_by_default(client, db_session):
    job = _mk_job(db_session)
    resp = client.get(f"/api/screening/jobs/{job.id}/scoring-weights")
    assert resp.status_code == 200
    data = resp.json()
    assert data["custom"] is False
    assert "skill_match" in data["weights"]


def test_get_job_weights_returns_custom_when_set(client, db_session):
    custom = {"skill_match": 60, "experience": 15, "seniority": 10, "education": 10, "industry": 5}
    job = _mk_job(db_session, scoring_weights=custom)
    resp = client.get(f"/api/screening/jobs/{job.id}/scoring-weights")
    assert resp.status_code == 200
    data = resp.json()
    assert data["custom"] is True
    assert data["weights"]["skill_match"] == 60


# ── API: PUT /scoring-weights ─────────────────────────────────────────────────

def test_put_job_weights_sets_custom(client, db_session):
    job = _mk_job(db_session)
    payload = {"skill_match": 50, "experience": 20, "seniority": 10, "education": 10, "industry": 10}
    resp = client.put(f"/api/screening/jobs/{job.id}/scoring-weights", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["custom"] is True
    assert data["weights"]["skill_match"] == 50

    # Verify persisted in DB
    db_session.expire_all()
    job_db = db_session.query(Job).filter_by(id=job.id).one()
    assert job_db.scoring_weights["skill_match"] == 50


def test_put_job_weights_rejects_sum_not_100(client, db_session):
    job = _mk_job(db_session)
    payload = {"skill_match": 50, "experience": 20, "seniority": 10, "education": 10, "industry": 5}  # sum=95
    resp = client.put(f"/api/screening/jobs/{job.id}/scoring-weights", json=payload)
    assert resp.status_code == 422


def test_put_job_weights_rejects_sum_over_100(client, db_session):
    job = _mk_job(db_session)
    payload = {"skill_match": 50, "experience": 30, "seniority": 15, "education": 10, "industry": 10}  # sum=115
    resp = client.put(f"/api/screening/jobs/{job.id}/scoring-weights", json=payload)
    assert resp.status_code == 422


def test_put_job_weights_404(client, db_session):
    payload = {"skill_match": 35, "experience": 30, "seniority": 15, "education": 10, "industry": 10}
    resp = client.put("/api/screening/jobs/99999/scoring-weights", json=payload)
    assert resp.status_code == 404


# ── API: DELETE /scoring-weights ──────────────────────────────────────────────

def test_delete_job_weights_reverts_to_global(client, db_session):
    custom = {"skill_match": 60, "experience": 15, "seniority": 10, "education": 10, "industry": 5}
    job = _mk_job(db_session, scoring_weights=custom)

    resp = client.delete(f"/api/screening/jobs/{job.id}/scoring-weights")
    assert resp.status_code == 204

    db_session.expire_all()
    job_db = db_session.query(Job).filter_by(id=job.id).one()
    assert job_db.scoring_weights is None

    # GET should now report custom=False
    resp2 = client.get(f"/api/screening/jobs/{job.id}/scoring-weights")
    assert resp2.json()["custom"] is False


# ── scoring: weights_hash uses effective weights ──────────────────────────────

@pytest.mark.asyncio
async def test_score_pair_uses_job_custom_weights(db_session):
    """Scoring two jobs with different weights produces different weights_hash."""
    resume = _mk_resume(db_session)
    job_a = _mk_job(db_session, title="A",
                    scoring_weights={"skill_match": 60, "experience": 15,
                                     "seniority": 10, "education": 10, "industry": 5})
    job_b = _mk_job(db_session, title="B",
                    scoring_weights={"skill_match": 20, "experience": 40,
                                     "seniority": 20, "education": 10, "industry": 10})

    svc = MatchingService(db_session)
    with NO_LLM:
        await svc.score_pair(resume.id, job_a.id)
        await svc.score_pair(resume.id, job_b.id)

    row_a = db_session.query(MatchingResult).filter_by(resume_id=resume.id, job_id=job_a.id).one()
    row_b = db_session.query(MatchingResult).filter_by(resume_id=resume.id, job_id=job_b.id).one()

    assert row_a.weights_hash != row_b.weights_hash


@pytest.mark.asyncio
async def test_weights_hash_equals_effective_weights_hash(db_session):
    """DB row weights_hash must equal compute_weights_hash(get_effective_weights(job))."""
    custom = {"skill_match": 50, "experience": 20, "seniority": 10, "education": 10, "industry": 10}
    resume = _mk_resume(db_session)
    job = _mk_job(db_session, scoring_weights=custom)

    with NO_LLM:
        await MatchingService(db_session).score_pair(resume.id, job.id)

    row = db_session.query(MatchingResult).filter_by(resume_id=resume.id, job_id=job.id).one()
    expected_hash = compute_weights_hash(get_effective_weights(job))
    assert row.weights_hash == expected_hash


# ── isolation: custom weights on Job A don't affect Job B ────────────────────

@pytest.mark.asyncio
async def test_custom_weights_job_a_no_spurious_stale_job_b(db_session, client):
    """Setting custom weights on Job A must NOT cause Job B's results to become stale."""
    resume = _mk_resume(db_session)
    job_a = _mk_job(db_session, title="A")
    job_b = _mk_job(db_session, title="B")

    with NO_LLM:
        await MatchingService(db_session).score_pair(resume.id, job_a.id)
        await MatchingService(db_session).score_pair(resume.id, job_b.id)

    # Confirm both are fresh
    resp_b_before = client.get(f"/api/matching/results?job_id={job_b.id}")
    assert resp_b_before.status_code == 200
    assert resp_b_before.json()["items"][0]["stale"] is False

    # Give Job A custom weights
    payload = {"skill_match": 60, "experience": 15, "seniority": 10, "education": 10, "industry": 5}
    client.put(f"/api/screening/jobs/{job_a.id}/scoring-weights", json=payload)

    # Job B should NOT be stale — it still uses global/default, and its row has global hash
    resp_b_after = client.get(f"/api/matching/results?job_id={job_b.id}")
    assert resp_b_after.status_code == 200
    assert resp_b_after.json()["items"][0]["stale"] is False


@pytest.mark.asyncio
async def test_custom_weights_causes_own_results_stale(db_session, client):
    """After setting custom weights on a job, its existing results become stale."""
    resume = _mk_resume(db_session)
    job = _mk_job(db_session)

    with NO_LLM:
        await MatchingService(db_session).score_pair(resume.id, job.id)

    resp_before = client.get(f"/api/matching/results?job_id={job.id}")
    assert resp_before.json()["items"][0]["stale"] is False

    # Set custom weights
    payload = {"skill_match": 60, "experience": 15, "seniority": 10, "education": 10, "industry": 5}
    client.put(f"/api/screening/jobs/{job.id}/scoring-weights", json=payload)

    # Now results are stale because stored hash is based on global weights
    resp_after = client.get(f"/api/matching/results?job_id={job.id}")
    assert resp_after.json()["items"][0]["stale"] is True
