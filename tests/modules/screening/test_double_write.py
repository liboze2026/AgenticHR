"""HITL approve → 双写扁平字段回填."""
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
    # resumes table (full baseline schema) required by migration 0007
    # (ALTER TABLE resumes ADD COLUMN seniority)
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


@pytest.fixture
def session(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    url = f"sqlite:///{db}"
    _seed_jobs_table(str(db))
    cfg = Config("migrations/alembic.ini")
    cfg.set_main_option("script_location", "migrations")
    cfg.set_main_option("sqlalchemy.url", url)
    command.stamp(cfg, "0001")
    command.upgrade(cfg, "head")
    engine = sa.create_engine(url, connect_args={"check_same_thread": False})
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr("app.database.engine", engine)
    from app.modules.screening import competency_service as cs
    monkeypatch.setattr(cs, "_session_factory", factory)
    yield factory


def test_apply_writes_competency_and_flat_fields(session):
    from app.modules.screening.models import Job
    from app.modules.screening.competency_service import apply_competency_to_job

    s = session()
    job = Job(title="后端")
    s.add(job); s.commit(); s.refresh(job)
    jid = job.id
    s.close()

    model = {
        "hard_skills": [
            {"name": "Python", "weight": 9, "must_have": True, "level": "精通"},
            {"name": "FastAPI", "weight": 7, "must_have": False, "level": "熟练"},
        ],
        "soft_skills": [],
        "experience": {"years_min": 3, "years_max": 7, "industries": [], "company_scale": None},
        "education": {"min_level": "本科", "preferred_level": None, "prestigious_bonus": False},
        "job_level": "P6",
        "bonus_items": [],
        "exclusions": [],
        "assessment_dimensions": [],
        "source_jd_hash": "abc",
        "extracted_at": "2026-04-20T10:00:00",
    }
    apply_competency_to_job(jid, model)

    s = session()
    job = s.query(Job).filter(Job.id == jid).first()
    assert job.competency_model_status == "approved"
    assert job.competency_model is not None
    assert job.education_min == "本科"
    assert job.work_years_min == 3
    assert job.work_years_max == 7
    assert "Python" in job.required_skills
    assert "FastAPI" not in job.required_skills  # must_have=False
    s.close()


def test_apply_handles_null_years_max(session):
    from app.modules.screening.models import Job
    from app.modules.screening.competency_service import apply_competency_to_job

    s = session()
    job = Job(title="x"); s.add(job); s.commit(); jid = job.id; s.close()

    model = {
        "hard_skills": [{"name": "Go", "weight": 8, "must_have": True, "level": "熟练"}],
        "soft_skills": [], "experience": {"years_min": 2, "years_max": None,
                                           "industries": [], "company_scale": None},
        "education": {"min_level": "本科"},
        "bonus_items": [], "exclusions": [], "assessment_dimensions": [],
        "source_jd_hash": "h", "extracted_at": "2026-04-20T10:00:00",
    }
    apply_competency_to_job(jid, model)

    s = session()
    job = s.query(Job).filter(Job.id == jid).first()
    assert job.work_years_min == 2
    assert job.work_years_max == 99
    s.close()


def test_apply_only_must_have_in_required_skills(session):
    from app.modules.screening.models import Job
    from app.modules.screening.competency_service import apply_competency_to_job

    s = session()
    job = Job(title="x"); s.add(job); s.commit(); jid = job.id; s.close()

    model = {
        "hard_skills": [
            {"name": "Python", "weight": 9, "must_have": True, "level": "精通"},
            {"name": "FastAPI", "weight": 6, "must_have": False, "level": "熟练"},
        ],
        "soft_skills": [], "experience": {"years_min": 0, "years_max": 99,
                                           "industries": [], "company_scale": None},
        "education": {"min_level": "本科"}, "bonus_items": [], "exclusions": [],
        "assessment_dimensions": [], "source_jd_hash": "h", "extracted_at": "2026-04-20T10:00:00",
    }
    apply_competency_to_job(jid, model)

    s = session()
    job = s.query(Job).filter(Job.id == jid).first()
    assert "Python" in job.required_skills
    assert "FastAPI" not in job.required_skills
    s.close()
