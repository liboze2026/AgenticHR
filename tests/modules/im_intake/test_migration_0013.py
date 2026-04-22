"""0013 迁移: intake_candidates.user_id + UNIQUE(user_id, boss_id)."""
import sqlite3
import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config


def _seed_m2_schema(db: str):
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


def test_0013_adds_user_id_and_swaps_unique_constraint(tmp_path):
    db = tmp_path / "t.db"
    _seed_m2_schema(str(db))
    cfg = _cfg(str(db))
    command.stamp(cfg, "0009")
    command.upgrade(cfg, "0012")

    eng = sa.create_engine(f"sqlite:///{db}", connect_args={"check_same_thread": False})
    with eng.begin() as c:
        c.execute(sa.text(
            "INSERT INTO intake_candidates (boss_id, name, intake_status, source) "
            "VALUES ('bxLegacy','legacy','collecting','plugin')"
        ))

    command.upgrade(cfg, "0013")

    insp = sa.inspect(eng)
    cols = {c["name"] for c in insp.get_columns("intake_candidates")}
    assert "user_id" in cols

    # Legacy row must have user_id = 0 (server_default backfill)
    with eng.begin() as c:
        legacy_uid = c.execute(sa.text(
            "SELECT user_id FROM intake_candidates WHERE boss_id='bxLegacy'"
        )).scalar()
    assert legacy_uid == 0

    # Indexes: ix_intake_candidates_user_boss must exist and be unique;
    # ix_intake_candidates_boss_id must exist and be NON-unique.
    idx = {ix["name"]: ix for ix in insp.get_indexes("intake_candidates")}
    assert "ix_intake_candidates_user_boss" in idx
    assert bool(idx["ix_intake_candidates_user_boss"]["unique"]) is True
    assert "ix_intake_candidates_user_id" in idx
    assert bool(idx["ix_intake_candidates_boss_id"]["unique"]) is False

    # Same boss_id allowed under different users
    with eng.begin() as c:
        c.execute(sa.text(
            "INSERT INTO intake_candidates (user_id, boss_id, name, intake_status, source) "
            "VALUES (1,'bxShared','A','collecting','plugin'), "
            "(2,'bxShared','B','collecting','plugin')"
        ))

    # Duplicate (user_id, boss_id) must fail
    with pytest.raises(Exception):
        with eng.begin() as c:
            c.execute(sa.text(
                "INSERT INTO intake_candidates (user_id, boss_id, name, intake_status, source) "
                "VALUES (1,'bxShared','dup','collecting','plugin')"
            ))


def test_0013_is_reversible(tmp_path):
    db = tmp_path / "t.db"
    _seed_m2_schema(str(db))
    cfg = _cfg(str(db))
    command.stamp(cfg, "0009")
    command.upgrade(cfg, "0013")
    command.downgrade(cfg, "0012")

    eng = sa.create_engine(f"sqlite:///{db}", connect_args={"check_same_thread": False})
    insp = sa.inspect(eng)
    cols = {c["name"] for c in insp.get_columns("intake_candidates")}
    assert "user_id" not in cols
    idx = {ix["name"]: ix for ix in insp.get_indexes("intake_candidates")}
    assert "ix_intake_candidates_boss_id" in idx
    assert bool(idx["ix_intake_candidates_boss_id"]["unique"]) is True
    assert "ix_intake_candidates_user_boss" not in idx
