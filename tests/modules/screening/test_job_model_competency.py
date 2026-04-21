"""Job 模型 F1 新字段."""
import pytest
from alembic import command
from alembic.config import Config
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from app.modules.screening.models import Job
from app.modules.screening.schemas import JobCreate, JobResponse


@pytest.fixture
def session(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    url = f"sqlite:///{db}"
    cfg = Config("migrations/alembic.ini")
    cfg.set_main_option("script_location", "migrations")
    cfg.set_main_option("sqlalchemy.url", url)
    # Need jobs + resumes tables pre-seeded: jobs for migration 0005 ALTER TABLE,
    # resumes for migration 0007 ALTER TABLE resumes ADD COLUMN seniority
    import sqlite3
    conn = sqlite3.connect(str(db))
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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS resumes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER DEFAULT 0,
            name VARCHAR(100) NOT NULL,
            phone VARCHAR(20) DEFAULT '',
            email VARCHAR(200) DEFAULT '',
            education VARCHAR(50) DEFAULT '',
            bachelor_school VARCHAR(200) DEFAULT '',
            master_school VARCHAR(200) DEFAULT '',
            phd_school VARCHAR(200) DEFAULT '',
            qr_code_path VARCHAR(500) DEFAULT '',
            work_years INTEGER DEFAULT 0,
            expected_salary_min REAL DEFAULT 0,
            expected_salary_max REAL DEFAULT 0,
            job_intention VARCHAR(200) DEFAULT '',
            skills TEXT DEFAULT '',
            work_experience TEXT DEFAULT '',
            project_experience TEXT DEFAULT '',
            self_evaluation TEXT DEFAULT '',
            source VARCHAR(50) DEFAULT '',
            raw_text TEXT DEFAULT '',
            pdf_path VARCHAR(500) DEFAULT '',
            status VARCHAR(20) DEFAULT 'passed',
            ai_parsed VARCHAR(10) DEFAULT 'no',
            ai_score REAL,
            ai_summary TEXT DEFAULT '',
            reject_reason VARCHAR(200) DEFAULT '',
            created_at DATETIME,
            updated_at DATETIME
        )
    """)
    conn.commit()
    conn.close()
    command.stamp(cfg, "0001")
    command.upgrade(cfg, "head")
    engine = sa.create_engine(url, connect_args={"check_same_thread": False})
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr("app.database.engine", engine)
    return factory()


def test_job_has_new_columns(session):
    job = Job(title="后端", jd_text="招聘后端", competency_model={"v": 1},
              competency_model_status="draft")
    session.add(job); session.commit(); session.refresh(job)
    assert job.jd_text == "招聘后端"
    assert job.competency_model == {"v": 1}
    assert job.competency_model_status == "draft"


def test_job_defaults_for_new_columns(session):
    job = Job(title="后端")
    session.add(job); session.commit(); session.refresh(job)
    assert job.jd_text == ""
    assert job.competency_model is None
    assert job.competency_model_status == "none"


def test_job_response_schema_has_competency_fields():
    data = JobResponse(
        id=1, user_id=0, title="x", department="", education_min="",
        work_years_min=0, work_years_max=99, salary_min=0, salary_max=0,
        required_skills="", soft_requirements="", greeting_templates="",
        is_active=True, jd_text="jd", competency_model={"v": 1},
        competency_model_status="draft",
    )
    assert data.jd_text == "jd"
    assert data.competency_model_status == "draft"


def test_job_create_allows_optional_competency():
    data = JobCreate(title="后端")
    assert data.jd_text == ""
    assert data.competency_model is None
