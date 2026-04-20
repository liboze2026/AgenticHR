"""验证 seed 技能被填入 skills 表."""
import sqlite3
from alembic import command
from alembic.config import Config


def _cfg(db: str) -> Config:
    cfg = Config("migrations/alembic.ini")
    cfg.set_main_option("script_location", "migrations")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db}")
    return cfg


def _seed_jobs(db: str):
    """0005 需要 jobs 表存在 (M2 baseline). 空 tmp DB 需要先手工建出."""
    conn = sqlite3.connect(db)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title VARCHAR(200) NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def test_seed_skills_inserted(tmp_path):
    db = tmp_path / "t.db"
    _seed_jobs(str(db))
    command.upgrade(_cfg(str(db)), "0006")

    conn = sqlite3.connect(str(db))
    count = conn.execute("SELECT COUNT(*) FROM skills WHERE source='seed'").fetchone()[0]
    assert count >= 50, f"expected >=50 seed skills, got {count}"

    python_row = conn.execute(
        "SELECT canonical_name, category FROM skills WHERE canonical_name='Python'"
    ).fetchone()
    assert python_row == ("Python", "language")

    python_aliases = conn.execute(
        "SELECT aliases FROM skills WHERE canonical_name='Python'"
    ).fetchone()[0]
    assert "python3" in python_aliases

    none_embed = conn.execute(
        "SELECT COUNT(*) FROM skills WHERE source='seed' AND embedding IS NULL"
    ).fetchone()[0]
    assert none_embed >= 50

    conn.close()


def _count(db):
    conn = sqlite3.connect(str(db))
    c = conn.execute("SELECT COUNT(*) FROM skills WHERE source='seed'").fetchone()[0]
    conn.close()
    return c


def test_seed_idempotent(tmp_path):
    """多次 upgrade-downgrade-upgrade 不会重复插入."""
    db = tmp_path / "t.db"
    _seed_jobs(str(db))
    cfg = _cfg(str(db))
    command.upgrade(cfg, "0006")
    count1 = _count(db)
    command.downgrade(cfg, "0005")
    command.upgrade(cfg, "0006")
    count2 = _count(db)
    assert count1 == count2
