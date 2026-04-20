"""验证 M2 老岗位 (competency_model=NULL) 筛选行为不变."""
import pytest
import sqlite3
from alembic import command
from alembic.config import Config
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker


def _seed_jobs_table(db: str):
    conn = sqlite3.connect(db)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER DEFAULT 0,
            title VARCHAR(200) NOT NULL,
            department VARCHAR(100) DEFAULT '',
            education_min VARCHAR(50) DEFAULT '',
            work_years_min INTEGER DEFAULT 0,
            work_years_max INTEGER DEFAULT 99,
            salary_min REAL DEFAULT 0,
            salary_max REAL DEFAULT 0,
            required_skills TEXT DEFAULT '',
            soft_requirements TEXT DEFAULT '',
            greeting_templates TEXT DEFAULT '',
            is_active BOOLEAN DEFAULT 1,
            created_at DATETIME,
            updated_at DATETIME
        )
    """)
    conn.commit()
    conn.close()


@pytest.fixture
def db(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    url = f"sqlite:///{db}"
    _seed_jobs_table(str(db))
    cfg = Config("migrations/alembic.ini")
    cfg.set_main_option("script_location", "migrations")
    cfg.set_main_option("sqlalchemy.url", url)
    command.stamp(cfg, "0001")
    command.upgrade(cfg, "0006")
    engine = sa.create_engine(url, connect_args={"check_same_thread": False})
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr("app.database.engine", engine)
    s = factory()
    # Ensure resumes table exists (Base metadata creation for resumes)
    from app.modules.resume.models import Resume
    from app.database import Base
    Base.metadata.create_all(bind=engine, tables=[Resume.__table__])
    return s


def test_flat_fields_still_filter_when_competency_model_null(db):
    from app.modules.screening.service import ScreeningService
    from app.modules.screening.models import Job
    from app.modules.resume.models import Resume

    job = Job(title="后端", education_min="本科", required_skills="Python,FastAPI",
               work_years_min=3, work_years_max=7)
    pass_resume = Resume(name="合格", education="本科", work_years=5,
                          skills="Python, FastAPI, Redis")
    fail_edu = Resume(name="学历差", education="大专", work_years=5, skills="Python,FastAPI")
    fail_skill = Resume(name="技能缺", education="本科", work_years=5, skills="Java")
    db.add_all([job, pass_resume, fail_edu, fail_skill]); db.commit()

    result = ScreeningService(db).screen_resumes(job.id)
    assert result["passed"] == 1
    assert result["rejected"] == 2
    passed = next(r for r in result["results"] if r["passed"])
    assert passed["resume_name"] == "合格"


def test_competency_model_drives_filter_when_present(db):
    from app.modules.screening.service import ScreeningService
    from app.modules.screening.models import Job
    from app.modules.resume.models import Resume

    comp = {
        "hard_skills": [{"name": "Rust", "weight": 9, "must_have": True, "level": "熟练"}],
        "soft_skills": [],
        "experience": {"years_min": 5, "years_max": None, "industries": [], "company_scale": None},
        "education": {"min_level": "硕士", "preferred_level": None, "prestigious_bonus": False},
        "job_level": "", "bonus_items": [], "exclusions": [],
        "assessment_dimensions": [],
        "source_jd_hash": "h", "extracted_at": "2026-04-20T10:00:00",
    }
    job = Job(title="x", competency_model=comp, competency_model_status="approved",
               education_min="本科", required_skills="Python", work_years_min=0)
    rust_hao = Resume(name="Rust 大哥", education="硕士", work_years=6, skills="Rust, Go")
    db.add_all([job, rust_hao]); db.commit()

    result = ScreeningService(db).screen_resumes(job.id)
    assert result["passed"] == 1


def test_rejected_if_hard_skill_missing_from_competency(db):
    from app.modules.screening.service import ScreeningService
    from app.modules.screening.models import Job
    from app.modules.resume.models import Resume

    comp = {
        "hard_skills": [{"name": "Rust", "weight": 9, "must_have": True, "level": "熟练"}],
        "soft_skills": [], "experience": {"years_min": 0, "years_max": None,
                                           "industries": [], "company_scale": None},
        "education": {"min_level": "本科"}, "job_level": "",
        "bonus_items": [], "exclusions": [], "assessment_dimensions": [],
        "source_jd_hash": "h", "extracted_at": "2026-04-20T10:00:00",
    }
    job = Job(title="x", competency_model=comp, competency_model_status="approved")
    no_rust = Resume(name="no_rust", education="本科", work_years=3, skills="Python")
    db.add_all([job, no_rust]); db.commit()

    result = ScreeningService(db).screen_resumes(job.id)
    assert result["passed"] == 0
    rejected = result["results"][0]
    assert any("Rust" in r for r in rejected["reject_reasons"])
