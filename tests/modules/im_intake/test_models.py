from datetime import datetime, timezone
from app.modules.im_intake.models import IntakeSlot
from app.modules.resume.models import Resume

def test_intake_slot_create_and_query(db_session):
    r = Resume(name="张三", boss_id="abc", intake_status="collecting")
    db_session.add(r); db_session.commit()
    s = IntakeSlot(
        resume_id=r.id, slot_key="arrival_date", slot_category="hard",
        value="下周一", source="regex",
        asked_at=datetime.now(timezone.utc), answered_at=datetime.now(timezone.utc),
        ask_count=1,
    )
    db_session.add(s); db_session.commit()
    assert IntakeSlot.__tablename__ == "intake_slots"
    rows = db_session.query(IntakeSlot).filter_by(resume_id=r.id).all()
    assert len(rows) == 1 and rows[0].slot_key == "arrival_date"

def test_resume_has_intake_fields():
    cols = Resume.__table__.columns.keys()
    for c in ("intake_status", "intake_started_at", "intake_completed_at", "job_id"):
        assert c in cols, f"missing {c}"
