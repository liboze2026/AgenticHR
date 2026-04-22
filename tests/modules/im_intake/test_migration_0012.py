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

    # Simulate a pre-F4 legacy row (intake_status was added in 0011 with a
    # NOT NULL default). Bypass the NOT NULL via writable_schema so the
    # filter `intake_status IS NOT NULL AND != 'complete'` is exercised.
    raw = sqlite3.connect(str(db))
    raw.execute("PRAGMA writable_schema = 1")
    raw.execute(
        "UPDATE sqlite_master SET sql = replace(sql, "
        "'intake_status VARCHAR(20) DEFAULT ''collecting'' NOT NULL', "
        "'intake_status VARCHAR(20) DEFAULT ''collecting''') "
        "WHERE type='table' AND name='resumes'"
    )
    raw.execute("PRAGMA writable_schema = 0")
    raw.commit()
    raw.close()

    eng = sa.create_engine(f"sqlite:///{db}", connect_args={"check_same_thread": False})
    with eng.begin() as c:
        # Seed: A collecting (moved), B complete (stays), C NULL intake_status
        # (pre-F4 legacy row, must also stay — filter is IS NOT NULL AND != 'complete').
        c.execute(sa.text(
            "INSERT INTO resumes (name, boss_id, intake_status) "
            "VALUES ('A','bx1','collecting'), "
            "('B','bx2','complete'), "
            "('C','bx3',NULL)"
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
            "SELECT name, boss_id, intake_status FROM resumes ORDER BY id"
        )).all()
        a_cid = c.execute(sa.text(
            "SELECT id FROM intake_candidates WHERE boss_id='bx1'"
        )).scalar()
        slot_cid = c.execute(sa.text(
            "SELECT candidate_id FROM intake_slots"
        )).scalar()
    assert [r[0] for r in ic_rows] == ["A"]
    # Both 'complete' (B) and NULL intake_status (C) must remain in resumes.
    assert [r[0] for r in r_rows] == ["B", "C"]
    assert slot_cid == a_cid


def test_0012_dedupes_duplicate_boss_ids(tmp_path):
    """Two non-complete resumes sharing the same boss_id should collapse to
    a single intake_candidates row; both original resumes rows get deleted,
    and any intake_slots row originally tied to either resume ends up pointing
    at the single surviving candidate."""
    db = tmp_path / "t.db"
    _seed_m2_schema(str(db))
    cfg = _cfg(str(db))
    command.stamp(cfg, "0009")
    command.upgrade(cfg, "0011")

    eng = sa.create_engine(f"sqlite:///{db}", connect_args={"check_same_thread": False})
    with eng.begin() as c:
        # Two non-complete resumes sharing the same boss_id. They must live
        # under different user_ids to sidestep the UNIQUE(user_id, boss_id)
        # constraint introduced in 0010 — the duplicate scenario this test
        # covers arises from multi-tenant data making the same boss_id appear
        # more than once in intake_candidates (which has UNIQUE(boss_id) only).
        c.execute(sa.text(
            "INSERT INTO resumes (user_id, name, boss_id, intake_status) "
            "VALUES (1,'Dup1','bxDup','collecting'), "
            "(2,'Dup2','bxDup','pending_human')"
        ))
        # A slot tied to the second (duplicate) resume — should get re-pointed
        # at the first-inserted candidate.
        c.execute(sa.text(
            "INSERT INTO intake_slots (resume_id, slot_key, slot_category, ask_count) "
            "VALUES (2,'arrival_date','hard',0)"
        ))

    command.upgrade(cfg, "0012")

    with eng.begin() as c:
        ic_rows = c.execute(sa.text(
            "SELECT id, boss_id FROM intake_candidates"
        )).all()
        r_count = c.execute(sa.text(
            "SELECT COUNT(*) FROM resumes WHERE boss_id='bxDup'"
        )).scalar()
        slot_cid = c.execute(sa.text(
            "SELECT candidate_id FROM intake_slots"
        )).scalar()
    assert len(ic_rows) == 1
    assert ic_rows[0][1] == "bxDup"
    assert r_count == 0
    assert slot_cid == ic_rows[0][0]


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
