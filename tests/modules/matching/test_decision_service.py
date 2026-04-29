"""spec 0429-D — decision_service 单测"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
import app.modules.auth.models  # noqa: F401
import app.modules.resume.models  # noqa: F401
import app.modules.screening.models  # noqa: F401
import app.modules.im_intake.candidate_model  # noqa: F401
import app.modules.im_intake.models  # noqa: F401
import app.modules.matching.decision_model  # noqa: F401

from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.matching.decision_model import JobCandidateDecision
from app.modules.matching.decision_service import (
    DecisionError,
    set_decision,
    get_decision,
    get_decisions_map_for_job,
)
from app.modules.screening.models import Job


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    # seed users via raw SQL (no User model needed)
    from sqlalchemy import text
    s.execute(text(
        "INSERT INTO users (id, username, password_hash, display_name, is_active, daily_cap) "
        "VALUES (1,'u1','x','U1',1,1000), (2,'u2','x','U2',1,1000)"
    ))
    s.commit()
    yield s
    s.close()


def _add_job(db, user_id=1, title="后端") -> Job:
    j = Job(user_id=user_id, title=title)
    db.add(j)
    db.commit()
    db.refresh(j)
    return j


def _add_candidate(db, user_id=1, boss_id="b1", name="张三") -> IntakeCandidate:
    c = IntakeCandidate(user_id=user_id, boss_id=boss_id, name=name, pdf_path="x.pdf")
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


class TestSetDecision:
    def test_set_passed_creates_row(self, db):
        job = _add_job(db)
        cand = _add_candidate(db)
        row = set_decision(db, user_id=1, job_id=job.id, candidate_id=cand.id, action="passed")
        assert row is not None
        assert row.action == "passed"
        assert row.job_id == job.id
        assert row.candidate_id == cand.id

    def test_set_rejected_creates_row(self, db):
        job = _add_job(db)
        cand = _add_candidate(db)
        row = set_decision(db, user_id=1, job_id=job.id, candidate_id=cand.id, action="rejected")
        assert row.action == "rejected"

    def test_set_none_clears_row(self, db):
        job = _add_job(db)
        cand = _add_candidate(db)
        set_decision(db, user_id=1, job_id=job.id, candidate_id=cand.id, action="passed")
        result = set_decision(db, user_id=1, job_id=job.id, candidate_id=cand.id, action=None)
        assert result is None
        assert get_decision(db, 1, job.id, cand.id) is None

    def test_set_none_idempotent_when_no_row(self, db):
        job = _add_job(db)
        cand = _add_candidate(db)
        result = set_decision(db, user_id=1, job_id=job.id, candidate_id=cand.id, action=None)
        assert result is None

    def test_upsert_replaces_action(self, db):
        job = _add_job(db)
        cand = _add_candidate(db)
        r1 = set_decision(db, user_id=1, job_id=job.id, candidate_id=cand.id, action="passed")
        r2 = set_decision(db, user_id=1, job_id=job.id, candidate_id=cand.id, action="rejected")
        assert r1.id == r2.id
        assert r2.action == "rejected"
        # only one row exists
        count = db.query(JobCandidateDecision).filter_by(job_id=job.id, candidate_id=cand.id).count()
        assert count == 1

    def test_invalid_action_raises(self, db):
        job = _add_job(db)
        cand = _add_candidate(db)
        with pytest.raises(DecisionError) as exc:
            set_decision(db, user_id=1, job_id=job.id, candidate_id=cand.id, action="foo")
        assert exc.value.code == "invalid_action"

    def test_other_user_job_not_found(self, db):
        job = _add_job(db, user_id=2)
        cand = _add_candidate(db, user_id=1)
        with pytest.raises(DecisionError) as exc:
            set_decision(db, user_id=1, job_id=job.id, candidate_id=cand.id, action="passed")
        assert exc.value.code == "job_not_found"

    def test_other_user_candidate_not_found(self, db):
        job = _add_job(db, user_id=1)
        cand = _add_candidate(db, user_id=2)
        with pytest.raises(DecisionError) as exc:
            set_decision(db, user_id=1, job_id=job.id, candidate_id=cand.id, action="passed")
        assert exc.value.code == "candidate_not_found"

    def test_nonexistent_job_404(self, db):
        cand = _add_candidate(db)
        with pytest.raises(DecisionError) as exc:
            set_decision(db, user_id=1, job_id=99999, candidate_id=cand.id, action="passed")
        assert exc.value.code == "job_not_found"

    def test_nonexistent_candidate_404(self, db):
        job = _add_job(db)
        with pytest.raises(DecisionError) as exc:
            set_decision(db, user_id=1, job_id=job.id, candidate_id=99999, action="passed")
        assert exc.value.code == "candidate_not_found"


class TestSameCandidateMultipleJobs:
    def test_independent_decisions_per_job(self, db):
        job1 = _add_job(db, title="后端")
        job2 = _add_job(db, title="前端")
        cand = _add_candidate(db)
        set_decision(db, user_id=1, job_id=job1.id, candidate_id=cand.id, action="passed")
        set_decision(db, user_id=1, job_id=job2.id, candidate_id=cand.id, action="rejected")
        m1 = get_decisions_map_for_job(db, 1, job1.id)
        m2 = get_decisions_map_for_job(db, 1, job2.id)
        assert m1[cand.id] == "passed"
        assert m2[cand.id] == "rejected"


class TestUserScoping:
    def test_get_decisions_map_only_returns_own_user(self, db):
        # user 1 + user 2 each have their own job/candidate
        job1 = _add_job(db, user_id=1)
        job2 = _add_job(db, user_id=2)
        c1 = _add_candidate(db, user_id=1, boss_id="b1")
        c2 = _add_candidate(db, user_id=2, boss_id="b2")
        set_decision(db, 1, job1.id, c1.id, "passed")
        set_decision(db, 2, job2.id, c2.id, "rejected")
        m_for_u1 = get_decisions_map_for_job(db, 1, job1.id)
        assert m_for_u1 == {c1.id: "passed"}
        m_for_u2 = get_decisions_map_for_job(db, 2, job2.id)
        assert m_for_u2 == {c2.id: "rejected"}


class TestCascadeOnCandidateDelete:
    def test_decision_row_removed_when_candidate_deleted(self, db):
        job = _add_job(db)
        cand = _add_candidate(db)
        set_decision(db, 1, job.id, cand.id, "passed")
        # enable FK enforcement on this in-memory engine
        from sqlalchemy import text
        db.execute(text("PRAGMA foreign_keys=ON"))
        db.delete(cand)
        db.commit()
        assert db.query(JobCandidateDecision).count() == 0
