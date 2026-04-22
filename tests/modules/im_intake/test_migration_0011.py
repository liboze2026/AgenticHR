"""0011 迁移: intake_slots 表 + resumes.intake_* 字段."""
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


@pytest.fixture
def migrated_db(tmp_path):
    db = tmp_path / "t.db"
    _seed_m2_schema(str(db))
    cfg = _cfg(str(db))
    command.stamp(cfg, "0009")
    command.upgrade(cfg, "0011")
    return sa.create_engine(f"sqlite:///{db}", connect_args={"check_same_thread": False})


def test_intake_slots_table_exists(migrated_db):
    insp = sa.inspect(migrated_db)
    assert "intake_slots" in insp.get_table_names()
    cols = {c["name"] for c in insp.get_columns("intake_slots")}
    expected = {
        "id", "resume_id", "slot_key", "slot_category", "value",
        "asked_at", "answered_at", "ask_count", "last_ask_text",
        "source", "question_meta", "created_at", "updated_at",
    }
    assert expected.issubset(cols), f"missing: {expected - cols}"


def test_intake_slots_unique_resume_key(migrated_db):
    insp = sa.inspect(migrated_db)
    idxs = insp.get_indexes("intake_slots")
    uq = [i for i in idxs if i.get("unique") and set(i["column_names"]) == {"resume_id", "slot_key"}]
    assert len(uq) == 1, f"expected unique(resume_id, slot_key), got {idxs}"


def test_intake_slots_helper_indexes(migrated_db):
    insp = sa.inspect(migrated_db)
    idx_names = {i["name"] for i in insp.get_indexes("intake_slots")}
    assert "idx_intake_resume" in idx_names
    assert "idx_intake_answered" in idx_names


def test_resumes_intake_columns(migrated_db):
    insp = sa.inspect(migrated_db)
    cols = {c["name"] for c in insp.get_columns("resumes")}
    assert {"intake_status", "intake_started_at", "intake_completed_at", "job_id"}.issubset(cols)


def test_resumes_intake_status_default(migrated_db):
    with migrated_db.connect() as conn:
        info = conn.execute(sa.text("PRAGMA table_info(resumes)")).fetchall()
    cols = {r[1]: r for r in info}
    assert "intake_status" in cols
    default = cols["intake_status"][4]
    assert str(default).strip("'\"") == "collecting"


def test_migration_is_reversible(tmp_path):
    db = tmp_path / "t.db"
    _seed_m2_schema(str(db))
    cfg = _cfg(str(db))
    command.stamp(cfg, "0009")
    command.upgrade(cfg, "0011")
    command.downgrade(cfg, "0010")
    eng = sa.create_engine(f"sqlite:///{db}", connect_args={"check_same_thread": False})
    insp = sa.inspect(eng)
    assert "intake_slots" not in insp.get_table_names()
    cols = {c["name"] for c in insp.get_columns("resumes")}
    assert "intake_status" not in cols
    assert "job_id" not in cols
