"""简历库/匹配视图服务单元测试"""
import pytest
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
import app.modules.auth.models  # noqa: F401
import app.modules.resume.models  # noqa: F401
import app.modules.screening.models  # noqa: F401
import app.modules.im_intake.candidate_model  # noqa: F401
import app.modules.im_intake.models  # noqa: F401

from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.im_intake.models import IntakeSlot
from app.modules.im_intake.templates import HARD_SLOT_KEYS
from app.modules.screening.models import Job

from app.modules.resume.intake_view_service import (
    list_resume_library,
    list_matched_for_job,
    candidate_to_resume_dict,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


def _add_candidate(db, user_id=1, boss_id="b", name="张三",
                   pdf_path="data/x.pdf", filled_slots=HARD_SLOT_KEYS,
                   education="本科", bachelor_school="清华大学",
                   school_tier="985", source="plugin") -> IntakeCandidate:
    c = IntakeCandidate(
        user_id=user_id, boss_id=boss_id, name=name,
        pdf_path=pdf_path, intake_status="collecting",
        education=education,
        bachelor_school=bachelor_school,
        school_tier=school_tier,
        source=source,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    for key in filled_slots:
        slot = IntakeSlot(
            candidate_id=c.id, slot_key=key, slot_category="hard",
            value="filled-value", ask_count=1,
        )
        db.add(slot)
    db.commit()
    return c


def _add_job(db, user_id=1, education_min="", school_tier_min=""):
    job = Job(
        user_id=user_id, title="后端工程师",
        education_min=education_min,
        school_tier_min=school_tier_min,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


class TestResumeLibrary:
    def test_complete_candidate_appears(self, db):
        c = _add_candidate(db)
        result = list_resume_library(db, user_id=1)
        assert result["total"] == 1
        assert result["items"][0]["id"] == c.id
        assert result["items"][0]["name"] == "张三"

    def test_no_pdf_excluded(self, db):
        _add_candidate(db, pdf_path="")
        result = list_resume_library(db, user_id=1)
        assert result["total"] == 0

    def test_missing_one_hard_slot_excluded(self, db):
        # 只填 2 个 hard slot
        _add_candidate(db, filled_slots=("arrival_date", "free_slots"))
        result = list_resume_library(db, user_id=1)
        assert result["total"] == 0

    def test_zero_slots_excluded(self, db):
        _add_candidate(db, filled_slots=())
        result = list_resume_library(db, user_id=1)
        assert result["total"] == 0

    def test_user_scoping(self, db):
        _add_candidate(db, user_id=1, boss_id="b1")
        _add_candidate(db, user_id=2, boss_id="b2")
        r1 = list_resume_library(db, user_id=1)
        r2 = list_resume_library(db, user_id=2)
        assert r1["total"] == 1
        assert r2["total"] == 1

    def test_keyword_search(self, db):
        _add_candidate(db, name="王五", boss_id="b1")
        _add_candidate(db, name="李四", boss_id="b2")
        result = list_resume_library(db, user_id=1, keyword="王五")
        assert result["total"] == 1
        assert result["items"][0]["name"] == "王五"

    def test_empty_value_slot_excluded(self, db):
        c = _add_candidate(db, filled_slots=())
        # 加 3 个 slot 但 value 为空字符串
        for key in HARD_SLOT_KEYS:
            db.add(IntakeSlot(
                candidate_id=c.id, slot_key=key, slot_category="hard",
                value="", ask_count=1,
            ))
        db.commit()
        result = list_resume_library(db, user_id=1)
        assert result["total"] == 0

    def test_dict_shape_complete(self, db):
        c = _add_candidate(db)
        result = list_resume_library(db, user_id=1)
        item = result["items"][0]
        for key in ("id", "name", "phone", "email", "education", "bachelor_school",
                    "school_tier", "status", "intake_status", "boss_id",
                    "created_at", "updated_at", "reject_reason"):
            assert key in item, f"missing key: {key}"


class TestMatchedForJob:
    def test_no_requirement_returns_all_complete(self, db):
        _add_candidate(db, boss_id="b1", school_tier="", education="")
        _add_candidate(db, boss_id="b2", school_tier="985", education="本科")
        job = _add_job(db, education_min="", school_tier_min="")
        rows = list_matched_for_job(db, user_id=1, job_id=job.id)
        assert len(rows) == 2

    def test_education_gate_filters(self, db):
        _add_candidate(db, boss_id="b1", education="本科")
        _add_candidate(db, boss_id="b2", education="硕士")
        job = _add_job(db, education_min="硕士")
        rows = list_matched_for_job(db, user_id=1, job_id=job.id)
        names_or_ids = [r["education"] for r in rows]
        assert names_or_ids == ["硕士"]

    def test_school_tier_gate_filters(self, db):
        _add_candidate(db, boss_id="b1", school_tier="qs_top200")
        _add_candidate(db, boss_id="b2", school_tier="985")
        job = _add_job(db, school_tier_min="211")
        rows = list_matched_for_job(db, user_id=1, job_id=job.id)
        # 只有 985 通过 211 门槛
        assert len(rows) == 1
        assert rows[0]["school_tier"] == "985"

    def test_both_gates(self, db):
        _add_candidate(db, boss_id="b1", education="硕士", school_tier="qs_top200")
        _add_candidate(db, boss_id="b2", education="本科", school_tier="985")
        _add_candidate(db, boss_id="b3", education="硕士", school_tier="985")
        job = _add_job(db, education_min="硕士", school_tier_min="985")
        rows = list_matched_for_job(db, user_id=1, job_id=job.id)
        # 仅 b3 通过两道门槛
        assert len(rows) == 1
        assert rows[0]["education"] == "硕士"
        assert rows[0]["school_tier"] == "985"

    def test_incomplete_candidate_not_matched(self, db):
        _add_candidate(db, boss_id="b1", filled_slots=("arrival_date",),
                       education="博士", school_tier="985")
        job = _add_job(db, education_min="本科")
        rows = list_matched_for_job(db, user_id=1, job_id=job.id)
        assert rows == []

    def test_unknown_job_returns_empty(self, db):
        _add_candidate(db)
        rows = list_matched_for_job(db, user_id=1, job_id=99999)
        assert rows == []

    def test_user_scoping(self, db):
        _add_candidate(db, user_id=1, boss_id="b1")
        _add_candidate(db, user_id=2, boss_id="b2")
        job1 = _add_job(db, user_id=1)
        job2 = _add_job(db, user_id=2)
        r1 = list_matched_for_job(db, user_id=1, job_id=job1.id)
        r2 = list_matched_for_job(db, user_id=1, job_id=job2.id)
        assert len(r1) == 1
        assert r2 == []  # 用户 1 看不到用户 2 的岗位


class TestSimplexLibraryEqualsAllMatched:
    def test_resume_library_is_union_of_matched_when_no_gates(self, db):
        """简历库 == 所有岗位无门槛时的匹配候选人母集"""
        _add_candidate(db, boss_id="b1", education="本科", school_tier="qs_top200")
        _add_candidate(db, boss_id="b2", education="硕士", school_tier="985")
        _add_candidate(db, boss_id="b3", education="博士", school_tier="")
        job = _add_job(db, education_min="", school_tier_min="")
        lib = list_resume_library(db, user_id=1)
        matched = list_matched_for_job(db, user_id=1, job_id=job.id)
        assert lib["total"] == len(matched) == 3
