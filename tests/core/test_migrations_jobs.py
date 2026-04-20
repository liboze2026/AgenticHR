"""验证 jobs 表扩展 3 列."""
import sqlite3
from alembic import command
from alembic.config import Config


def _cfg(db: str) -> Config:
    cfg = Config("migrations/alembic.ini")
    cfg.set_main_option("script_location", "migrations")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db}")
    return cfg


def _seed_old_schema(db: str):
    """模拟 M2 老 DB: jobs 表已存在, 只有扁平字段."""
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
    conn.execute("INSERT INTO jobs (title, education_min) VALUES ('old_job', '本科')")
    conn.commit()
    conn.close()


def test_jobs_columns_added(tmp_path):
    db = tmp_path / "t.db"
    _seed_old_schema(str(db))

    cfg = _cfg(str(db))
    command.stamp(cfg, "0004")
    command.upgrade(cfg, "0005")

    conn = sqlite3.connect(str(db))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    assert "jd_text" in cols
    assert "competency_model" in cols
    assert "competency_model_status" in cols

    row = conn.execute(
        "SELECT title, jd_text, competency_model, competency_model_status FROM jobs"
    ).fetchone()
    assert row[0] == "old_job"
    assert row[1] == ""
    assert row[2] is None
    assert row[3] == "none"
    conn.close()


def test_jobs_downgrade_removes_columns(tmp_path):
    db = tmp_path / "t.db"
    _seed_old_schema(str(db))

    cfg = _cfg(str(db))
    command.stamp(cfg, "0004")
    command.upgrade(cfg, "0005")
    command.downgrade(cfg, "0004")

    conn = sqlite3.connect(str(db))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    assert "jd_text" not in cols
    assert "competency_model" not in cols
    assert "competency_model_status" not in cols
    conn.close()
