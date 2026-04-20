"""core.hitl.service — HITL task CRUD + state transitions."""
import pytest
from alembic import command
from alembic.config import Config
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def svc(tmp_path, monkeypatch):
    from app.core.hitl.service import HitlService, InvalidHitlStateError
    db = tmp_path / "t.db"
    url = f"sqlite:///{db}"
    cfg = Config("migrations/alembic.ini")
    cfg.set_main_option("script_location", "migrations")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "0004")  # audit_events + hitl_tasks exist by 0004
    engine = sa.create_engine(url, connect_args={"check_same_thread": False})
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr("app.database.engine", engine)
    from app.core.hitl import service as svc_mod
    monkeypatch.setattr(svc_mod, "_session_factory", factory)
    from app.core.audit import logger as audit_mod
    monkeypatch.setattr(audit_mod, "_session_factory", factory)
    return HitlService()


def test_create_task(svc):
    tid = svc.create(
        f_stage="F1_competency_review",
        entity_type="job",
        entity_id=1,
        payload={"draft": {"hard_skills": []}},
    )
    assert tid > 0
    task = svc.get(tid)
    assert task["status"] == "pending"
    assert task["payload"] == {"draft": {"hard_skills": []}}


def test_list_filters(svc):
    svc.create("F1_competency_review", "job", 1, {})
    svc.create("F1_skill_classification", "skill", 2, {})
    svc.create("F1_competency_review", "job", 3, {})

    all_tasks = svc.list()
    assert len(all_tasks) == 3

    comp = svc.list(stage="F1_competency_review")
    assert len(comp) == 2

    pending = svc.list(status="pending")
    assert len(pending) == 3


def test_approve_transitions_status(svc):
    tid = svc.create("F1_competency_review", "job", 1, {})
    svc.approve(tid, reviewer_id=99, note="looks good")
    task = svc.get(tid)
    assert task["status"] == "approved"
    assert task["reviewer_id"] == 99
    assert task["reviewed_at"] is not None
    assert task["note"] == "looks good"


def test_reject_requires_note(svc):
    tid = svc.create("F1_competency_review", "job", 1, {})
    with pytest.raises(ValueError, match="note"):
        svc.reject(tid, reviewer_id=99, note="")
    svc.reject(tid, reviewer_id=99, note="LLM 输出质量差")
    assert svc.get(tid)["status"] == "rejected"


def test_edit_writes_edited_payload(svc):
    tid = svc.create("F1_competency_review", "job", 1, {"v": 1})
    svc.edit(tid, reviewer_id=99, edited_payload={"v": 2}, note="adjusted weights")
    task = svc.get(tid)
    assert task["status"] == "edited"
    assert task["edited_payload"] == {"v": 2}
    assert task["payload"] == {"v": 1}


def test_cannot_double_approve(svc):
    from app.core.hitl.service import InvalidHitlStateError
    tid = svc.create("F1_competency_review", "job", 1, {})
    svc.approve(tid, reviewer_id=99)
    with pytest.raises(InvalidHitlStateError):
        svc.approve(tid, reviewer_id=99)


def test_get_not_found_returns_none(svc):
    assert svc.get(99999) is None


def test_approve_triggers_registered_callback(svc, monkeypatch):
    from app.core.hitl.service import register_approve_callback, _approve_callbacks
    # clean registry for test isolation
    monkeypatch.setattr("app.core.hitl.service._approve_callbacks", {})

    seen = []
    def cb(task):
        seen.append(task)

    register_approve_callback("F1_competency_review", cb)
    tid = svc.create("F1_competency_review", "job", 42, {"hard_skills": []})
    svc.approve(tid, reviewer_id=1)

    assert len(seen) == 1
    assert seen[0]["entity_id"] == 42
