"""验证 audit_events 表 migration 含 WORM 触发器."""
import sqlite3
import pytest
from alembic import command
from alembic.config import Config


def _cfg(db: str) -> Config:
    cfg = Config("migrations/alembic.ini")
    cfg.set_main_option("script_location", "migrations")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db}")
    return cfg


def test_audit_events_table_created(tmp_path):
    db = tmp_path / "t.db"
    command.upgrade(_cfg(str(db)), "0004")

    conn = sqlite3.connect(str(db))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(audit_events)").fetchall()}
    assert cols >= {
        "event_id", "f_stage", "action", "entity_type", "entity_id",
        "input_hash", "output_hash", "prompt_version",
        "model_name", "model_version", "reviewer_id",
        "created_at", "retention_until",
    }

    triggers = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='audit_events'"
    ).fetchall()}
    assert "audit_no_update" in triggers
    assert "audit_no_delete" in triggers
    conn.close()


def test_audit_worm_insert_allowed(tmp_path):
    db = tmp_path / "t.db"
    command.upgrade(_cfg(str(db)), "0004")
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO audit_events (event_id, f_stage, action, entity_type) "
        "VALUES ('u1', 'F1', 'extract', 'job')"
    )
    conn.commit()
    count = conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
    assert count == 1
    conn.close()


def test_audit_worm_update_forbidden(tmp_path):
    db = tmp_path / "t.db"
    command.upgrade(_cfg(str(db)), "0004")
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO audit_events (event_id, f_stage, action, entity_type) "
        "VALUES ('u1', 'F1', 'extract', 'job')"
    )
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError, match="WORM"):
        conn.execute("UPDATE audit_events SET action='tampered' WHERE event_id='u1'")
        conn.commit()
    conn.close()


def test_audit_worm_delete_forbidden(tmp_path):
    db = tmp_path / "t.db"
    command.upgrade(_cfg(str(db)), "0004")
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO audit_events (event_id, f_stage, action, entity_type) "
        "VALUES ('u1', 'F1', 'extract', 'job')"
    )
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError, match="WORM"):
        conn.execute("DELETE FROM audit_events WHERE event_id='u1'")
        conn.commit()
    conn.close()
