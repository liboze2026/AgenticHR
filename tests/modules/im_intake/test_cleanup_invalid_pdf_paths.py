"""TDD for A3: scripts/cleanup_invalid_pdf_paths.py.

Verify scan correctly classifies bad rows and apply mutates them.
"""
from pathlib import Path

from app.config import settings
from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.im_intake.models import IntakeSlot
from app.modules.resume.models import Resume
from scripts.cleanup_invalid_pdf_paths import is_valid_pdf_url, scan, apply_cleanup


def test_is_valid_pdf_url_accepts_http():
    assert is_valid_pdf_url("https://example.com/x.pdf")
    assert is_valid_pdf_url("http://example.com/x.pdf")


def test_is_valid_pdf_url_rejects_bare_filename():
    assert not is_valid_pdf_url("简历.pdf")
    assert not is_valid_pdf_url("resume.pdf")


def test_is_valid_pdf_url_accepts_existing_local_under_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "resume_storage_path", str(tmp_path))
    f = tmp_path / "ok.pdf"
    f.write_bytes(b"%PDF-1.4")
    assert is_valid_pdf_url(str(f))


def test_is_valid_pdf_url_rejects_missing_local(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "resume_storage_path", str(tmp_path))
    assert not is_valid_pdf_url(str(tmp_path / "ghost.pdf"))


def test_is_valid_pdf_url_rejects_outside_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "resume_storage_path", str(tmp_path))
    outside = tmp_path.parent / "elsewhere.pdf"
    outside.write_bytes(b"%PDF-1.4")
    assert not is_valid_pdf_url(str(outside))


def test_is_valid_pdf_url_treats_empty_as_clean():
    assert is_valid_pdf_url("")
    assert is_valid_pdf_url(None)


def _make_candidate(db, name, status, pdf_path, slot_value):
    c = IntakeCandidate(
        boss_id=f"bx_{name}",
        name=name,
        intake_status=status,
        source="plugin",
        pdf_path=pdf_path,
        user_id=1,
    )
    db.add(c)
    db.flush()
    s = IntakeSlot(
        candidate_id=c.id,
        slot_key="pdf",
        slot_category="pdf",
        value=slot_value,
        ask_count=2,
    )
    db.add(s)
    db.commit()
    return c


def test_scan_finds_bad_candidates(db_session):
    bad = _make_candidate(db_session, "陆昊男", "complete", "简历.pdf", "简历.pdf")
    good = _make_candidate(db_session, "OK人", "complete", "https://x.com/a.pdf",
                           "https://x.com/a.pdf")

    result = scan(db_session)
    bad_ids = {c.id for c in result["candidates"]}
    assert bad.id in bad_ids
    assert good.id not in bad_ids
    bad_slot_cids = {s.candidate_id for s in result["slots"]}
    assert bad.id in bad_slot_cids
    assert good.id not in bad_slot_cids


def test_apply_cleanup_clears_and_rolls_back(db_session):
    c = _make_candidate(db_session, "陆昊男2", "complete", "简历.pdf", "简历.pdf")
    cid = c.id

    result = scan(db_session)
    affected = apply_cleanup(db_session, result)
    assert affected["candidates"] == 1
    assert affected["status_rolled_back"] == 1
    assert affected["slots"] == 1

    db_session.expire_all()
    c2 = db_session.query(IntakeCandidate).filter_by(id=cid).one()
    assert c2.pdf_path in (None, "")
    assert c2.intake_status == "collecting"
    assert c2.intake_completed_at is None
    s = db_session.query(IntakeSlot).filter_by(candidate_id=cid, slot_key="pdf").one()
    assert s.value == ""
    assert s.ask_count == 0


def test_apply_cleanup_leaves_valid_rows_untouched(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "resume_storage_path", str(tmp_path))
    real = tmp_path / "ok.pdf"
    real.write_bytes(b"%PDF-1.4")
    keep = _make_candidate(db_session, "保留", "complete", str(real), str(real))

    result = scan(db_session)
    apply_cleanup(db_session, result)

    db_session.expire_all()
    c = db_session.query(IntakeCandidate).filter_by(id=keep.id).one()
    assert c.pdf_path == str(real)
    assert c.intake_status == "complete"


def test_apply_cleanup_handles_resume_rows(db_session):
    r = Resume(name="脏简历", pdf_path="简历.pdf", user_id=1)
    db_session.add(r)
    db_session.commit()

    result = scan(db_session)
    bad_resume_ids = {x.id for x in result["resumes"]}
    assert r.id in bad_resume_ids

    apply_cleanup(db_session, result)
    db_session.expire_all()
    r2 = db_session.query(Resume).filter_by(id=r.id).one()
    assert r2.pdf_path == ""
