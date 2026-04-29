"""IntakeCandidate PDF 解析与字段写入"""
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
import app.modules.im_intake.candidate_model  # noqa: F401
import app.modules.im_intake.models  # noqa: F401
import app.modules.auth.models  # noqa: F401
from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.im_intake.intake_pdf_parser import (
    compute_school_tier,
    extract_basic_fields,
    parse_and_fill,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


def _candidate(db, **kwargs) -> IntakeCandidate:
    defaults = dict(user_id=1, boss_id="b1", name="张三", intake_status="collecting")
    defaults.update(kwargs)
    c = IntakeCandidate(**defaults)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


class TestComputeSchoolTier:
    def test_no_schools_returns_empty(self):
        c = IntakeCandidate(boss_id="b", name="x", user_id=1)
        assert compute_school_tier(c) == ""

    def test_picks_highest_degree(self):
        c = IntakeCandidate(boss_id="b", name="x", user_id=1)
        c.bachelor_school = "北京邮电大学"  # 211
        c.master_school = "清华大学"  # 985
        # 硕士 > 本科，应取硕士的 985
        assert compute_school_tier(c) == "985"

    def test_falls_back_to_lower_degree(self):
        c = IntakeCandidate(boss_id="b", name="x", user_id=1)
        c.bachelor_school = "清华大学"  # 985
        c.master_school = ""  # 无
        assert compute_school_tier(c) == "985"

    def test_phd_takes_priority(self):
        c = IntakeCandidate(boss_id="b", name="x", user_id=1)
        c.bachelor_school = "清华大学"  # 985
        c.phd_school = "某不知名学校"  # 无等级
        # 博士最高，但学校无等级；compute 应该取最高带等级的学校
        # 设计：扫描博士 → 硕士 → 本科，第一个有 tier 的返回
        assert compute_school_tier(c) == "985"

    def test_qs_overseas(self):
        c = IntakeCandidate(boss_id="b", name="x", user_id=1)
        c.master_school = "麻省理工学院"
        assert compute_school_tier(c) == "qs_top200"


class TestExtractBasicFields:
    def test_skip_when_no_pdf_path(self, db):
        c = _candidate(db)
        ok = extract_basic_fields(c, db)
        assert ok is False
        assert c.phone == ""

    def test_skip_when_remote_url(self, db):
        c = _candidate(db, pdf_path="https://example.com/foo.pdf")
        ok = extract_basic_fields(c, db)
        assert ok is False  # URL 暂不支持下载

    def test_extracts_phone_email_education(self, db, tmp_path):
        c = _candidate(db, pdf_path=str(tmp_path / "fake.pdf"))
        sample = "张三 13800138000 zhang@example.com 本科 北京邮电大学"
        with patch("app.modules.im_intake.intake_pdf_parser.parse_pdf", return_value=sample):
            ok = extract_basic_fields(c, db)
        assert ok is True
        assert c.phone == "13800138000"
        assert c.email == "zhang@example.com"
        assert c.education == "本科"
        assert c.raw_text == sample

    def test_does_not_overwrite_existing(self, db, tmp_path):
        c = _candidate(db, pdf_path=str(tmp_path / "fake.pdf"),
                       phone="13900000000", email="old@x.com")
        sample = "张三 13800138000 zhang@example.com 本科"
        with patch("app.modules.im_intake.intake_pdf_parser.parse_pdf", return_value=sample):
            extract_basic_fields(c, db)
        assert c.phone == "13900000000"
        assert c.email == "old@x.com"


class TestParseAndFill:
    def test_skips_if_no_pdf(self, db):
        c = _candidate(db)
        result = parse_and_fill(c, db, ai_provider=None)
        assert result is False

    def test_basic_only_no_ai(self, db, tmp_path):
        c = _candidate(db, pdf_path=str(tmp_path / "fake.pdf"))
        sample = "李四 13700000001 li@x.com 硕士"
        with patch("app.modules.im_intake.intake_pdf_parser.parse_pdf", return_value=sample):
            result = parse_and_fill(c, db, ai_provider=None)
        assert result is True
        assert c.phone == "13700000001"
        assert c.education == "硕士"
        # AI 未跑：学校字段为空
        assert c.bachelor_school == ""
        assert c.school_tier == ""

    def test_ai_fills_schools_and_tier(self, db, tmp_path):
        c = _candidate(db, pdf_path=str(tmp_path / "fake.pdf"))
        sample = "王五 13600000002 wang@x.com 硕士 北京邮电大学 清华大学"

        ai_response = {
            "name": "王五",
            "phone": "13600000002",
            "email": "wang@x.com",
            "education": "硕士",
            "bachelor_school": "北京邮电大学",
            "master_school": "清华大学",
            "phd_school": "",
            "work_years": 3,
            "skills": "Python,Java",
        }

        class FakeAI:
            def is_configured(self):
                return True

        ai = FakeAI()
        with patch("app.modules.im_intake.intake_pdf_parser.parse_pdf", return_value=sample), \
             patch("app.modules.im_intake.intake_pdf_parser.is_image_pdf", return_value=False), \
             patch("app.modules.im_intake.intake_pdf_parser.ai_parse_resume",
                   new=AsyncMock(return_value=ai_response)):
            result = parse_and_fill(c, db, ai_provider=ai)

        assert result is True
        assert c.bachelor_school == "北京邮电大学"
        assert c.master_school == "清华大学"
        assert c.school_tier == "985"  # 硕士清华
        assert c.ai_parsed == "yes"
