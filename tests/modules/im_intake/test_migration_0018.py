"""Verify migration 0018 creates intake_user_settings and is reversible."""
import sqlite3
import sqlalchemy as sa
from alembic import command
from alembic.config import Config


def _seed_base(db: str):
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT,
            username VARCHAR(50), password_hash VARCHAR(200),
            display_name VARCHAR(100) DEFAULT '', is_active BOOLEAN DEFAULT 1,
            created_at DATETIME);
        CREATE TABLE jobs (id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER DEFAULT 0, title VARCHAR(200), department VARCHAR(100) DEFAULT '',
            education_min VARCHAR(50) DEFAULT '', work_years_min INTEGER DEFAULT 0,
            work_years_max INTEGER DEFAULT 99, salary_min REAL DEFAULT 0, salary_max REAL DEFAULT 0,
            required_skills TEXT DEFAULT '', soft_requirements TEXT DEFAULT '',
            greeting_templates TEXT DEFAULT '', is_active BOOLEAN DEFAULT 1,
            created_at DATETIME, updated_at DATETIME);
        CREATE TABLE resumes (id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER DEFAULT 0, name VARCHAR(100), phone VARCHAR(20) DEFAULT '',
            email VARCHAR(200) DEFAULT '', education VARCHAR(50) DEFAULT '',
            created_at DATETIME, updated_at DATETIME);
    """)
    conn.commit()
    conn.close()


def _cfg(db: str) -> Config:
    cfg = Config("migrations/alembic.ini")
    cfg.set_main_option("script_location", "migrations")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db}")
    return cfg


def test_0018_upgrade_creates_table(tmp_path):
    db = tmp_path / "t.db"
    _seed_base(str(db))
    cfg = _cfg(str(db))
    command.stamp(cfg, "0009")
    command.upgrade(cfg, "0018")

    eng = sa.create_engine(f"sqlite:///{db}", connect_args={"check_same_thread": False})
    insp = sa.inspect(eng)

    assert "intake_user_settings" in insp.get_table_names()
    cols = {c["name"] for c in insp.get_columns("intake_user_settings")}
    assert {"user_id", "enabled", "target_count", "created_at", "updated_at"} <= cols


def test_0018_downgrade_drops_table(tmp_path):
    db = tmp_path / "t.db"
    _seed_base(str(db))
    cfg = _cfg(str(db))
    command.stamp(cfg, "0009")
    command.upgrade(cfg, "0018")
    command.downgrade(cfg, "0017")

    eng = sa.create_engine(f"sqlite:///{db}", connect_args={"check_same_thread": False})
    insp = sa.inspect(eng)
    assert "intake_user_settings" not in insp.get_table_names()
