"""Migration 0016: jobs.batch_collect_criteria column"""
import pytest
from sqlalchemy import create_engine, inspect, text
from alembic.config import Config
from alembic import command


def _alembic_cfg(db_url: str) -> Config:
    cfg = Config("migrations/alembic.ini")
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def _seed_jobs(conn):
    conn.execute(text(
        "CREATE TABLE IF NOT EXISTS users "
        "(id INTEGER PRIMARY KEY, username TEXT, password_hash TEXT, "
        "display_name TEXT, is_active INTEGER DEFAULT 1, daily_cap INTEGER DEFAULT 1000)"
    ))
    conn.execute(text(
        "INSERT OR IGNORE INTO users (id, username, password_hash) VALUES (1,'u','x')"
    ))
    conn.execute(text(
        "CREATE TABLE IF NOT EXISTS jobs "
        "(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER DEFAULT 0, "
        "title TEXT NOT NULL, department TEXT DEFAULT '', "
        "education_min TEXT DEFAULT '', work_years_min INTEGER DEFAULT 0, "
        "work_years_max INTEGER DEFAULT 99, salary_min REAL DEFAULT 0, "
        "salary_max REAL DEFAULT 0, required_skills TEXT DEFAULT '', "
        "soft_requirements TEXT DEFAULT '', greeting_templates TEXT DEFAULT '', "
        "is_active INTEGER DEFAULT 1, created_at DATETIME, updated_at DATETIME, "
        "jd_text TEXT DEFAULT '', competency_model JSON, "
        "competency_model_status TEXT DEFAULT 'none', "
        "scoring_weights JSON, greet_threshold INTEGER DEFAULT 60)"
    ))


def test_migration_0016_upgrade_adds_column(tmp_path):
    db_url = f"sqlite:///{tmp_path}/test_0016.db"
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    with engine.begin() as conn:
        _seed_jobs(conn)
    cfg = _alembic_cfg(db_url)
    command.stamp(cfg, "0015")
    command.upgrade(cfg, "0016")
    inspector = inspect(engine)
    cols = [c["name"] for c in inspector.get_columns("jobs")]
    assert "batch_collect_criteria" in cols
    engine.dispose()


def test_migration_0016_downgrade_removes_column(tmp_path):
    db_url = f"sqlite:///{tmp_path}/test_0016_down.db"
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    with engine.begin() as conn:
        _seed_jobs(conn)
    cfg = _alembic_cfg(db_url)
    command.stamp(cfg, "0015")
    command.upgrade(cfg, "0016")
    command.downgrade(cfg, "0015")
    inspector = inspect(engine)
    cols = [c["name"] for c in inspector.get_columns("jobs")]
    assert "batch_collect_criteria" not in cols
    engine.dispose()
