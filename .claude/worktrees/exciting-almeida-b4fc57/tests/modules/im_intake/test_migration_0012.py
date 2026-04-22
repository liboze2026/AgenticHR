"""0012 迁移: intake_candidates 表 + 非 complete 行迁移."""
import sqlite3
import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config


def _seed_m2_schema(db: str):
    """模拟 baseline 至 0010 需要的表."""
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


def test_0012_creates_intake_candidates_and_moves_non_complete_rows(tmp_path):
    db = tmp_path / "t.db"
    _seed_m2_schema(str(db))
    cfg = _cfg(str(db))
    command.stamp(cfg, "0009")
    command.upgrade(cfg, "0011")

    eng = sa.create_engine(f"sqlite:///{db}", connect_args={"check_same_thread": False})
    with eng.begin() as c:
        c.execute(sa.text(
            "INSERT INTO resumes (name, boss_id, intake_status) "
            "VALUES ('A','bx1','collecting'), "
            "('B','bx2','complete')"
        ))
        c.execute(sa.text(
            "INSERT INTO intake_slots (resume_id, slot_key, slot_category, ask_count) "
            "VALUES (1,'arrival_date','hard',0)"
        ))

    command.upgrade(cfg, "0012")

    insp = sa.inspect(eng)
    assert "intake_candidates" in insp.get_table_names()
    with eng.begin() as c:
        ic_rows = c.execute(sa.text(
            "SELECT name, boss_id, intake_status FROM intake_candidates"
        )).all()
        r_rows = c.execute(sa.text(
            "SELECT name, boss_id, intake_status FROM resumes"
        )).all()
        slot_rows = c.execute(sa.text(
            "SELECT candidate_id FROM intake_slots"
        )).all()
    assert [r[0] for r in ic_rows] == ["A"]
    assert [r[0] for r in r_rows] == ["B"]
    assert slot_rows and slot_rows[0][0] is not None


def test_0012_is_reversible(tmp_path):
    db = tmp_path / "t.db"
    _seed_m2_schema(str(db))
    cfg = _cfg(str(db))
    command.stamp(cfg, "0009")
    command.upgrade(cfg, "0012")
    command.downgrade(cfg, "0011")
    eng = sa.create_engine(f"sqlite:///{db}", connect_args={"check_same_thread": False})
    insp = sa.inspect(eng)
    assert "intake_candidates" not in insp.get_table_names()
    cols = {c["name"] for c in insp.get_columns("intake_slots")}
    assert "resume_id" in cols
    assert "candidate_id" not in cols
