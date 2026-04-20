"""验证 hitl_tasks 表 migration."""
import sqlite3
from alembic import command
from alembic.config import Config


def _cfg(db: str) -> Config:
    cfg = Config("migrations/alembic.ini")
    cfg.set_main_option("script_location", "migrations")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db}")
    return cfg


def test_hitl_tasks_table_created(tmp_path):
    db = tmp_path / "t.db"
    command.upgrade(_cfg(str(db)), "0003")

    conn = sqlite3.connect(str(db))
    cols = {r[1]: r[2] for r in conn.execute("PRAGMA table_info(hitl_tasks)").fetchall()}
    assert set(cols.keys()) >= {
        "id", "f_stage", "entity_type", "entity_id",
        "payload", "status", "edited_payload",
        "reviewer_id", "reviewed_at", "note", "created_at",
    }
    assert cols["status"] == "TEXT"
    assert cols["payload"] == "JSON"

    idxs = {r[1] for r in conn.execute(
        "SELECT * FROM sqlite_master WHERE type='index' AND tbl_name='hitl_tasks'"
    ).fetchall()}
    assert "idx_hitl_status" in idxs
    assert "idx_hitl_stage" in idxs
    conn.close()


def test_hitl_tasks_roundtrip(tmp_path):
    db = tmp_path / "t.db"
    cfg = _cfg(str(db))
    command.upgrade(cfg, "0003")
    command.downgrade(cfg, "0002")

    conn = sqlite3.connect(str(db))
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert "hitl_tasks" not in tables
    conn.close()
