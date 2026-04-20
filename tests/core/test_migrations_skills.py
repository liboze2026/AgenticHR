"""验证 skills 表 migration 结构."""
import sqlite3
import tempfile
from pathlib import Path

from alembic import command
from alembic.config import Config


def _make_alembic_cfg(db_path: str) -> Config:
    cfg = Config("migrations/alembic.ini")
    cfg.set_main_option("script_location", "migrations")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    return cfg


def test_skills_table_created_with_indexes(tmp_path):
    db = tmp_path / "t.db"
    cfg = _make_alembic_cfg(str(db))
    command.upgrade(cfg, "0002")

    conn = sqlite3.connect(str(db))
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert "skills" in tables

    cols = {r[1]: r[2] for r in conn.execute("PRAGMA table_info(skills)").fetchall()}
    assert cols["canonical_name"] == "TEXT"
    assert cols["aliases"] == "JSON"
    assert cols["category"] == "TEXT"
    assert cols["embedding"] == "BLOB"
    assert cols["source"] == "TEXT"
    assert cols["pending_classification"] == "BOOLEAN"
    assert cols["usage_count"] == "INTEGER"

    idxs = {r[1] for r in conn.execute(
        "SELECT * FROM sqlite_master WHERE type='index' AND tbl_name='skills'"
    ).fetchall()}
    assert "idx_skills_category" in idxs
    assert "idx_skills_pending" in idxs

    conn.close()


def test_skills_downgrade_removes_table(tmp_path):
    db = tmp_path / "t.db"
    cfg = _make_alembic_cfg(str(db))
    command.upgrade(cfg, "0002")
    command.downgrade(cfg, "0001")

    conn = sqlite3.connect(str(db))
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert "skills" not in tables
    conn.close()
