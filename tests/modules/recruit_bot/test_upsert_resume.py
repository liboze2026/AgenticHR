"""upsert_resume_by_boss_id — UNIQUE(user_id, boss_id) 幂等."""
import sqlite3
import pytest
from alembic import command
from alembic.config import Config
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker


def _seed_m2_schema(db: str):
    """模拟 M2 baseline: users/jobs/resumes 已存在, 为迁移提供 ALTER 目标."""
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username VARCHAR(50) UNIQUE NOT NULL,
            password_hash VARCHAR(200) NOT NULL,
            display_name VARCHAR(100) DEFAULT '',
            is_active BOOLEAN DEFAULT 1,
            created_at DATETIME
        );
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
        );
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
            seniority VARCHAR(20) NOT NULL DEFAULT '',
            created_at DATETIME,
            updated_at DATETIME
        );
    """)
    conn.commit()
    conn.close()


@pytest.fixture
def db(tmp_path, monkeypatch):
    dbp = tmp_path / "t.db"
    _seed_m2_schema(str(dbp))
    url = f"sqlite:///{dbp}"
    cfg = Config("migrations/alembic.ini")
    cfg.set_main_option("script_location", "migrations")
    cfg.set_main_option("sqlalchemy.url", url)
    command.stamp(cfg, "0009")
    command.upgrade(cfg, "0010")
    engine = sa.create_engine(url, connect_args={"check_same_thread": False})
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr("app.database.engine", engine)
    session = factory()
    yield session
    session.close()


def _mk_candidate(boss_id="xyz001", name="张三"):
    from app.modules.recruit_bot.schemas import ScrapedCandidate
    return ScrapedCandidate(
        name=name, boss_id=boss_id, age=28,
        education="本科", school="XX 大学", major="计算机",
        intended_job="后端", work_years=3,
        skill_tags=["Python", "Redis"],
        raw_text="full text",
    )


def test_upsert_creates_new_resume(db):
    from app.modules.recruit_bot.service import upsert_resume_by_boss_id
    r = upsert_resume_by_boss_id(db, user_id=1, candidate=_mk_candidate())
    assert r.id > 0
    assert r.name == "张三"
    assert r.boss_id == "xyz001"
    assert r.user_id == 1
    assert r.source == "boss_zhipin"
    assert r.skills == "Python,Redis"
    assert r.greet_status == "none"


def test_upsert_idempotent_same_boss_id(db):
    from app.modules.recruit_bot.service import upsert_resume_by_boss_id
    r1 = upsert_resume_by_boss_id(db, user_id=1, candidate=_mk_candidate())
    r2 = upsert_resume_by_boss_id(
        db, user_id=1, candidate=_mk_candidate(name="张三改名"),
    )
    assert r1.id == r2.id
    assert r2.name == "张三改名"  # 字段更新


def test_upsert_different_users_different_rows(db):
    from app.modules.recruit_bot.service import upsert_resume_by_boss_id
    r1 = upsert_resume_by_boss_id(db, user_id=1, candidate=_mk_candidate())
    r2 = upsert_resume_by_boss_id(db, user_id=2, candidate=_mk_candidate())
    assert r1.id != r2.id


def test_upsert_does_not_clobber_greet_status(db):
    """既有 greet_status='greeted' 的 resume 再 upsert 不把状态重置."""
    from app.modules.recruit_bot.service import upsert_resume_by_boss_id
    from app.modules.resume.models import Resume
    r1 = upsert_resume_by_boss_id(db, user_id=1, candidate=_mk_candidate())
    r1.greet_status = "greeted"
    db.commit()
    r2 = upsert_resume_by_boss_id(db, user_id=1, candidate=_mk_candidate(name="新名"))
    assert r2.greet_status == "greeted"  # 未被清


def test_upsert_skill_tags_csv_conversion(db):
    from app.modules.recruit_bot.service import upsert_resume_by_boss_id
    from app.modules.recruit_bot.schemas import ScrapedCandidate
    c = ScrapedCandidate(
        name="李四", boss_id="zzz",
        skill_tags=["Java", "Spring", "Redis"],
    )
    r = upsert_resume_by_boss_id(db, user_id=1, candidate=c)
    assert r.skills == "Java,Spring,Redis"


def test_upsert_raw_text_includes_all_fields(db):
    """raw_text 回填成调试用的 summary, 所有字段拼接."""
    from app.modules.recruit_bot.service import upsert_resume_by_boss_id
    c = _mk_candidate()
    r = upsert_resume_by_boss_id(db, user_id=1, candidate=c)
    assert "Python" in r.raw_text
    assert "张三" in r.raw_text or "后端" in r.raw_text
