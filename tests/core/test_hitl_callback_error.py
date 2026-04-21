"""HITL callback 失败 → 任务回退到 pending + 抛 HitlCallbackError."""
import pytest
from alembic import command
from alembic.config import Config
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def svc(tmp_path, monkeypatch):
    from app.core.hitl.service import HitlService
    db = tmp_path / "t.db"
    url = f"sqlite:///{db}"
    cfg = Config("migrations/alembic.ini")
    cfg.set_main_option("script_location", "migrations")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "0004")
    engine = sa.create_engine(url, connect_args={"check_same_thread": False})
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr("app.database.engine", engine)
    from app.core.hitl import service as svc_mod
    monkeypatch.setattr(svc_mod, "_session_factory", factory)
    from app.core.audit import logger as audit_mod
    monkeypatch.setattr(audit_mod, "_session_factory", factory)
    monkeypatch.setattr("app.core.hitl.service._approve_callbacks", {})
    return HitlService()


def test_approve_callback_failure_reverts_to_pending_and_raises(svc):
    from app.core.hitl.service import register_approve_callback, HitlCallbackError

    def bad_cb(task):
        raise RuntimeError("apply_competency_to_job: job 1 not found")

    register_approve_callback("F1_competency_review", bad_cb)
    tid = svc.create("F1_competency_review", "job", 1, {"hard_skills": []})

    with pytest.raises(HitlCallbackError) as exc_info:
        svc.approve(tid, reviewer_id=99, note="ok")

    assert "apply_competency_to_job" in str(exc_info.value)

    task = svc.get(tid)
    assert task["status"] == "pending"
    assert "callback failed" in (task["note"] or "").lower()


def test_edit_callback_failure_reverts_to_pending_and_raises(svc):
    from app.core.hitl.service import register_approve_callback, HitlCallbackError

    def bad_cb(task):
        raise RuntimeError("downstream write fail")

    register_approve_callback("F1_competency_review", bad_cb)
    tid = svc.create("F1_competency_review", "job", 1, {"v": 1})

    with pytest.raises(HitlCallbackError):
        svc.edit(tid, reviewer_id=99, edited_payload={"v": 2}, note="adjusted")

    task = svc.get(tid)
    assert task["status"] == "pending"
    assert "callback failed" in (task["note"] or "").lower()


def test_approve_callback_success_stays_approved(svc):
    from app.core.hitl.service import register_approve_callback

    ran = []

    def good_cb(task):
        ran.append(task["id"])

    register_approve_callback("F1_competency_review", good_cb)
    tid = svc.create("F1_competency_review", "job", 1, {"hard_skills": []})

    svc.approve(tid, reviewer_id=99, note="approved")

    task = svc.get(tid)
    assert task["status"] == "approved"
    assert task["note"] == "approved"
    assert ran == [tid]


def test_approve_multiple_callbacks_one_fails_reverts(svc):
    """多 callback 注册: 任一失败 → 回退 pending."""
    from app.core.hitl.service import register_approve_callback, HitlCallbackError

    first_ran = []

    def good_cb(task):
        first_ran.append(task["id"])

    def bad_cb(task):
        raise RuntimeError("second callback blew up")

    register_approve_callback("F1_competency_review", good_cb)
    register_approve_callback("F1_competency_review", bad_cb)
    tid = svc.create("F1_competency_review", "job", 1, {})

    with pytest.raises(HitlCallbackError):
        svc.approve(tid, reviewer_id=99)

    task = svc.get(tid)
    assert task["status"] == "pending"
    assert first_ran == [tid]


def test_audit_log_records_callback_failure(svc):
    """callback 失败应写 audit_events action=hitl_approve_callback_failed."""
    from app.core.hitl.service import register_approve_callback, HitlCallbackError
    from app.core.audit.models import AuditEvent

    def bad_cb(task):
        raise RuntimeError("boom")

    register_approve_callback("F1_competency_review", bad_cb)
    tid = svc.create("F1_competency_review", "job", 1, {})

    with pytest.raises(HitlCallbackError):
        svc.approve(tid, reviewer_id=99)

    from app.core.audit import logger as audit_mod
    session = audit_mod._session_factory()
    try:
        events = session.query(AuditEvent).filter(
            AuditEvent.action == "hitl_approve_callback_failed"
        ).all()
        assert len(events) >= 1
    finally:
        session.close()
