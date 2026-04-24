from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.im_intake.settings_service import (
    get_or_create, update, complete_count, is_running,
)


def test_get_or_create_returns_defaults(db_session):
    s = get_or_create(db_session, user_id=1)
    assert s.user_id == 1
    assert s.enabled is False
    assert s.target_count == 0


def test_get_or_create_is_idempotent(db_session):
    s1 = get_or_create(db_session, user_id=1)
    s2 = get_or_create(db_session, user_id=1)
    assert s1.user_id == s2.user_id  # same row


def test_update_partial_fields(db_session):
    get_or_create(db_session, user_id=1)
    s = update(db_session, user_id=1, enabled=True, target_count=50)
    assert s.enabled is True
    assert s.target_count == 50

    s2 = update(db_session, user_id=1, enabled=False)  # keeps target
    assert s2.enabled is False
    assert s2.target_count == 50


def test_complete_count_filters_by_user_and_status(db_session):
    db_session.add_all([
        IntakeCandidate(user_id=1, boss_id="a", intake_status="complete", source="plugin"),
        IntakeCandidate(user_id=1, boss_id="b", intake_status="complete", source="plugin"),
        IntakeCandidate(user_id=1, boss_id="c", intake_status="collecting", source="plugin"),
        IntakeCandidate(user_id=2, boss_id="d", intake_status="complete", source="plugin"),
    ])
    db_session.commit()
    assert complete_count(db_session, user_id=1) == 2
    assert complete_count(db_session, user_id=2) == 1


def test_is_running_requires_enabled_and_under_target(db_session):
    get_or_create(db_session, user_id=1)
    assert is_running(db_session, user_id=1) is False  # disabled by default

    update(db_session, user_id=1, enabled=True, target_count=2)
    assert is_running(db_session, user_id=1) is True  # 0 complete < 2

    db_session.add_all([
        IntakeCandidate(user_id=1, boss_id="x", intake_status="complete", source="plugin"),
        IntakeCandidate(user_id=1, boss_id="y", intake_status="complete", source="plugin"),
    ])
    db_session.commit()
    assert is_running(db_session, user_id=1) is False  # 2 >= 2 → done


def test_is_running_zero_target_means_not_running(db_session):
    update(db_session, user_id=1, enabled=True, target_count=0)
    assert is_running(db_session, user_id=1) is False  # no target set = don't auto-run


def test_is_running_does_not_write_row_for_unknown_user(db_session):
    from app.modules.im_intake.settings_model import IntakeUserSettings
    assert is_running(db_session, user_id=999) is False
    # verify no ghost row was inserted
    assert db_session.query(IntakeUserSettings).filter_by(user_id=999).first() is None
