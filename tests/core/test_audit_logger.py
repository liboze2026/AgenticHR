"""core.audit.logger — WORM 审计."""
import hashlib
import json
from datetime import datetime, timezone

import pytest

from app.core.audit.logger import log_event, compute_hash
from app.core.audit.models import AuditEvent


@pytest.fixture(autouse=True)
def _clean_db(tmp_path, monkeypatch):
    """每个测试用独立 SQLite + alembic migration."""
    import sqlalchemy as sa
    from alembic import command
    from alembic.config import Config

    db_path = tmp_path / "audit.db"
    url = f"sqlite:///{db_path}"

    cfg = Config("migrations/alembic.ini")
    cfg.set_main_option("script_location", "migrations")
    cfg.set_main_option("sqlalchemy.url", url)
    # audit_events created by 0004; skipping 0005+ since they depend on pre-existing jobs table
    command.upgrade(cfg, "0004")

    new_engine = sa.create_engine(url, connect_args={"check_same_thread": False})
    monkeypatch.setattr("app.database.engine", new_engine)
    from app.core.audit import logger as audit_logger
    monkeypatch.setattr(audit_logger, "_session_factory",
                        sa.orm.sessionmaker(bind=new_engine))
    yield new_engine


def test_log_event_inserts_row(_clean_db):
    event_id = log_event(
        f_stage="F1_competency_review",
        action="extract",
        entity_type="job",
        entity_id=1,
        input_payload={"jd": "demo"},
        output_payload={"skills": ["Python"]},
        prompt_version="f1_v1",
        model_name="glm-4-flash",
    )
    assert isinstance(event_id, str)
    assert len(event_id) == 36

    import sqlalchemy as sa
    with _clean_db.connect() as conn:
        row = conn.execute(sa.text("SELECT * FROM audit_events WHERE event_id=:id"),
                           {"id": event_id}).mappings().one()
    assert row["action"] == "extract"
    assert row["entity_type"] == "job"
    assert row["entity_id"] == 1
    assert row["prompt_version"] == "f1_v1"
    assert row["model_name"] == "glm-4-flash"
    assert len(row["input_hash"]) == 64
    assert len(row["output_hash"]) == 64


def test_log_event_hashes_deterministic():
    h1 = compute_hash({"a": 1, "b": 2})
    h2 = compute_hash({"b": 2, "a": 1})
    assert h1 == h2


def test_log_event_null_entity_id(_clean_db):
    eid = log_event(f_stage="F1", action="extract_fail", entity_type="job", entity_id=None)
    assert eid


def test_log_event_writes_payload_file(tmp_path, monkeypatch, _clean_db):
    from app.core.audit import logger as audit_logger
    monkeypatch.setattr(audit_logger, "AUDIT_DIR", str(tmp_path / "audit"))
    eid = log_event(
        f_stage="F1", action="extract", entity_type="job", entity_id=1,
        input_payload={"big": "data"}, output_payload={"r": 1},
    )
    path = tmp_path / "audit" / f"{eid}.json"
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["input"] == {"big": "data"}
    assert data["output"] == {"r": 1}


def test_audit_update_forbidden(_clean_db):
    log_event(f_stage="F1", action="extract", entity_type="job", entity_id=1)
    import sqlalchemy as sa
    with _clean_db.connect() as conn:
        with pytest.raises(Exception, match="WORM"):
            conn.execute(sa.text("UPDATE audit_events SET action='x'"))
            conn.commit()
