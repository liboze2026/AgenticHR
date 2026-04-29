"""TDD for Bug A2: collect-chat must validate body.pdf_url before persisting.

Without validation, a stray title string like "简历.pdf" gets stored as pdf_path,
later causing /api/resumes/{id}/pdf to 404 (file does not exist).
"""
from pathlib import Path

import pytest

from app.config import settings
from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.im_intake.models import IntakeSlot


def _post(client, **overrides):
    payload = {
        "boss_id": "bxPdfVal",
        "name": "PDF校验测试",
        "messages": [{"sender_id": "bxPdfVal", "content": "你好"}],
        "pdf_present": True,
    }
    payload.update(overrides)
    r = client.post("/api/intake/collect-chat", json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def test_valid_local_path_is_accepted(client, db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "resume_storage_path", str(tmp_path))
    pdf_file = tmp_path / "real.pdf"
    pdf_file.write_bytes(b"%PDF-1.4\n%fake")

    data = _post(client, pdf_url=str(pdf_file))
    cid = data["candidate_id"]
    db_session.expire_all()
    c = db_session.query(IntakeCandidate).get(cid)
    assert c.pdf_path, "expected pdf_path to be persisted"
    assert Path(c.pdf_path).resolve() == pdf_file.resolve()
    pdf_slot = db_session.query(IntakeSlot).filter_by(candidate_id=cid, slot_key="pdf").one()
    assert Path(pdf_slot.value).resolve() == pdf_file.resolve()


def test_valid_http_url_is_accepted(client, db_session):
    data = _post(client, pdf_url="https://example.com/resume.pdf", boss_id="bxHttp")
    cid = data["candidate_id"]
    db_session.expire_all()
    c = db_session.query(IntakeCandidate).get(cid)
    assert c.pdf_path == "https://example.com/resume.pdf"


def test_bare_filename_is_rejected(client, db_session):
    """Regression: '简历.pdf' was the bug-inducing fallback from extension card title."""
    data = _post(client, pdf_url="简历.pdf", boss_id="bxBareName")
    cid = data["candidate_id"]
    db_session.expire_all()
    c = db_session.query(IntakeCandidate).get(cid)
    assert c.pdf_path in (None, "")
    pdf_slot = db_session.query(IntakeSlot).filter_by(candidate_id=cid, slot_key="pdf").one_or_none()
    if pdf_slot:
        assert pdf_slot.value in (None, "")


def test_path_traversal_outside_storage_is_rejected(client, db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "resume_storage_path", str(tmp_path))
    outside = tmp_path.parent / "outside.pdf"
    outside.write_bytes(b"%PDF-1.4")
    data = _post(client, pdf_url=str(outside), boss_id="bxOutside")
    cid = data["candidate_id"]
    db_session.expire_all()
    c = db_session.query(IntakeCandidate).get(cid)
    assert c.pdf_path in (None, "")


def test_local_path_in_storage_but_file_missing_is_rejected(client, db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "resume_storage_path", str(tmp_path))
    ghost = tmp_path / "ghost.pdf"  # not created
    data = _post(client, pdf_url=str(ghost), boss_id="bxGhost")
    cid = data["candidate_id"]
    db_session.expire_all()
    c = db_session.query(IntakeCandidate).get(cid)
    assert c.pdf_path in (None, "")


def test_invalid_pdf_url_does_not_crash_collect_chat(client, db_session):
    """Smoke: pipeline keeps moving when pdf_url is rejected — candidate gets
    persisted, next_action is one of the legal types, and pdf_path stays clean."""
    data = _post(client, pdf_url="简历.pdf", boss_id="bxNoCrash")
    assert data["candidate_id"] > 0
    assert data["next_action"]["type"] in (
        "send_hard", "request_pdf", "complete", "wait_pdf",
        "send_soft", "mark_pending_human", "abandon", "wait_reply",
    )
    db_session.expire_all()
    c = db_session.query(IntakeCandidate).get(data["candidate_id"])
    assert c.pdf_path in (None, "")
