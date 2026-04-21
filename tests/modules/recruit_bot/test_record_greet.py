"""record_greet_sent — 幂等 + 审计."""
import pytest
from datetime import datetime, timezone


def _mk_resume(db, user_id=1, boss_id="b1", greet_status="pending_greet"):
    from app.modules.resume.models import Resume
    r = Resume(
        user_id=user_id, name="张三", boss_id=boss_id,
        source="boss_zhipin", greet_status=greet_status,
    )
    db.add(r); db.commit(); db.refresh(r)
    return r


def test_record_greet_success(db):
    from app.modules.recruit_bot.service import record_greet_sent
    from app.modules.resume.models import Resume
    r = _mk_resume(db)
    record_greet_sent(db, user_id=1, resume_id=r.id, success=True)
    db.expire(r); r = db.query(Resume).filter_by(id=r.id).first()
    assert r.greet_status == "greeted"
    assert r.greeted_at is not None


def test_record_greet_failed(db):
    from app.modules.recruit_bot.service import record_greet_sent
    from app.modules.resume.models import Resume
    r = _mk_resume(db)
    record_greet_sent(db, user_id=1, resume_id=r.id, success=False, error_msg="button_not_found")
    db.expire(r); r = db.query(Resume).filter_by(id=r.id).first()
    assert r.greet_status == "failed"
    assert r.greeted_at is None


def test_record_greet_idempotent_on_already_greeted(db):
    from app.modules.recruit_bot.service import record_greet_sent
    from app.modules.resume.models import Resume
    r = _mk_resume(db, greet_status="greeted")
    r.greeted_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
    db.commit()
    record_greet_sent(db, user_id=1, resume_id=r.id, success=True)
    db.expire(r); r = db.query(Resume).filter_by(id=r.id).first()
    assert r.greet_status == "greeted"
    assert r.greeted_at.year == 2020


def test_record_greet_foreign_resume_raises(db):
    from app.modules.recruit_bot.service import record_greet_sent
    r = _mk_resume(db, user_id=999)
    with pytest.raises(ValueError):
        record_greet_sent(db, user_id=1, resume_id=r.id, success=True)


def test_record_greet_writes_audit_success(db):
    from app.modules.recruit_bot.service import record_greet_sent
    from app.core.audit.models import AuditEvent
    r = _mk_resume(db)
    record_greet_sent(db, user_id=1, resume_id=r.id, success=True)
    events = db.query(AuditEvent).filter(AuditEvent.f_stage == "F3_greet_sent").all()
    assert len(events) >= 1


def test_record_greet_writes_audit_failed_with_error(db, tmp_path, monkeypatch):
    # AuditEvent row 只存 hash, 实际 payload 外置到 {AUDIT_DIR}/{event_id}.json;
    # 把 AUDIT_DIR 指向 tmp_path 后, 读文件验证 error_msg 被正确落盘.
    from app.core.audit import logger as audit_logger
    monkeypatch.setattr(audit_logger, "AUDIT_DIR", str(tmp_path / "audit"))
    from app.modules.recruit_bot.service import record_greet_sent
    from app.core.audit.models import AuditEvent
    import json
    from pathlib import Path
    r = _mk_resume(db)
    record_greet_sent(db, user_id=1, resume_id=r.id, success=False, error_msg="risk_detected")
    events = db.query(AuditEvent).filter(AuditEvent.f_stage == "F3_greet_failed").all()
    assert len(events) >= 1
    ev = events[0]
    payload_path = Path(tmp_path / "audit") / f"{ev.event_id}.json"
    assert payload_path.exists()
    data = json.loads(payload_path.read_text(encoding="utf-8"))
    assert "risk_detected" in str(data.get("output") or {})
