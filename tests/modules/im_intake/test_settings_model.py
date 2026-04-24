from app.modules.im_intake.settings_model import IntakeUserSettings


def test_model_fields_present():
    """Smoke: class imports and has the expected SQLAlchemy columns."""
    cols = {c.name for c in IntakeUserSettings.__table__.columns}
    assert cols == {"user_id", "enabled", "target_count", "created_at", "updated_at"}


def test_model_defaults(db_session):
    s = IntakeUserSettings(user_id=42)
    db_session.add(s)
    db_session.commit()
    db_session.refresh(s)
    assert s.enabled is False
    assert s.target_count == 0
