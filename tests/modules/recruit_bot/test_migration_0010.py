"""0010 迁移落字段 + UNIQUE(user_id, boss_id)."""
import sqlite3
import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config


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
            created_at DATETIME,
            updated_at DATETIME
        );
    """)
    conn.commit()
    conn.close()


def _cfg(db: str) -> Config:
    cfg = Config("migrations/alembic.ini")
    cfg.set_main_option("script_location", "migrations")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db}")
    return cfg


@pytest.fixture
def migrated_db(tmp_path):
    db = tmp_path / "t.db"
    _seed_m2_schema(str(db))
    cfg = _cfg(str(db))
    command.stamp(cfg, "0009")
    command.upgrade(cfg, "0010")
    return sa.create_engine(f"sqlite:///{db}", connect_args={"check_same_thread": False})


def test_users_daily_cap_column(migrated_db):
    with migrated_db.connect() as conn:
        info = conn.execute(sa.text("PRAGMA table_info(users)")).fetchall()
    cols = {r[1]: r for r in info}
    assert "daily_cap" in cols
    # SQLite PRAGMA 可能把 server_default 以 '1000' / "1000" / 1000 多种形式呈现，都算默认值=1000
    default = cols["daily_cap"][4]
    assert str(default).strip("'\"") == "1000"


def test_jobs_greet_threshold_column(migrated_db):
    with migrated_db.connect() as conn:
        info = conn.execute(sa.text("PRAGMA table_info(jobs)")).fetchall()
    cols = {r[1]: r for r in info}
    assert "greet_threshold" in cols


def test_resumes_boss_fields(migrated_db):
    with migrated_db.connect() as conn:
        info = conn.execute(sa.text("PRAGMA table_info(resumes)")).fetchall()
    cols = {r[1] for r in info}
    assert {"boss_id", "greet_status", "greeted_at"} <= cols


def test_resumes_unique_user_boss(migrated_db):
    with migrated_db.connect() as conn:
        idxs = conn.execute(sa.text("SELECT name FROM sqlite_master WHERE type='index'")).fetchall()
    names = {r[0] for r in idxs}
    assert "ix_resumes_user_boss" in names


def test_migration_is_reversible(tmp_path):
    db = tmp_path / "t.db"
    _seed_m2_schema(str(db))
    cfg = _cfg(str(db))
    command.stamp(cfg, "0009")
    command.upgrade(cfg, "0010")
    command.downgrade(cfg, "0009")
    eng = sa.create_engine(f"sqlite:///{db}", connect_args={"check_same_thread": False})
    with eng.connect() as conn:
        info = conn.execute(sa.text("PRAGMA table_info(resumes)")).fetchall()
    cols = {r[1] for r in info}
    assert "boss_id" not in cols
    assert "greet_status" not in cols
