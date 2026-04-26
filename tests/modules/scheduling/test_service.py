"""面试安排业务逻辑测试"""
from datetime import datetime, timezone, timedelta

from app.modules.resume.models import Resume
from app.modules.scheduling.service import SchedulingService
from app.modules.scheduling.schemas import (
    InterviewerCreate,
    AvailabilityCreate,
    InterviewCreate,
    CandidateAvailability,
)


def _create_resume(db_session) -> Resume:
    """Helper: insert a minimal resume and return it."""
    resume = Resume(name="测试候选人", phone="13800000000")
    db_session.add(resume)
    db_session.commit()
    db_session.refresh(resume)
    return resume


def test_create_and_list_interviewers(db_session):
    service = SchedulingService(db_session)
    iv1 = service.create_interviewer(InterviewerCreate(name="张面试官", email="zhang@test.com"))
    iv2 = service.create_interviewer(InterviewerCreate(name="李面试官", department="技术部", email="li@test.com"))
    assert iv1.id is not None
    assert iv2.id is not None

    result = service.list_interviewers()
    assert result["total"] == 2
    assert len(result["items"]) == 2


def test_add_and_get_availability(db_session):
    service = SchedulingService(db_session)
    iv = service.create_interviewer(InterviewerCreate(name="王面试官", email="wang@test.com"))

    tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
    start = tomorrow.replace(hour=9, minute=0, second=0, microsecond=0)
    end = tomorrow.replace(hour=17, minute=0, second=0, microsecond=0)

    avail = service.add_availability(AvailabilityCreate(
        interviewer_id=iv.id, start_time=start, end_time=end,
    ))
    assert avail.id is not None

    avails = service.get_availability(iv.id)
    assert len(avails) == 1
    # SQLite strips timezone info, so compare without tzinfo
    assert avails[0].start_time.replace(tzinfo=None) == start.replace(tzinfo=None)


def test_match_slots(db_session):
    service = SchedulingService(db_session)
    iv = service.create_interviewer(InterviewerCreate(name="赵面试官", email="zhao@test.com"))

    tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
    iv_start = tomorrow.replace(hour=9, minute=0, second=0, microsecond=0)
    iv_end = tomorrow.replace(hour=12, minute=0, second=0, microsecond=0)

    service.add_availability(AvailabilityCreate(
        interviewer_id=iv.id, start_time=iv_start, end_time=iv_end,
    ))

    # Candidate available 10:00–12:00 => overlap 10:00–12:00 => 60-min slots at 10:00, 10:30, 11:00
    cand_start = tomorrow.replace(hour=10, minute=0, second=0, microsecond=0)
    cand_end = tomorrow.replace(hour=12, minute=0, second=0, microsecond=0)

    slots = service.match_slots(
        interviewer_id=iv.id,
        candidate_slots=[CandidateAvailability(start_time=cand_start, end_time=cand_end)],
        duration_minutes=60,
    )
    assert len(slots) == 3
    # Service returns naive datetimes (SQLite strips tzinfo)
    assert slots[0]["start_time"] == cand_start.replace(tzinfo=None)
    assert slots[1]["start_time"] == cand_start.replace(tzinfo=None) + timedelta(minutes=30)
    assert slots[2]["start_time"] == cand_start.replace(tzinfo=None) + timedelta(minutes=60)


def test_match_slots_with_existing_interview(db_session):
    service = SchedulingService(db_session)
    iv = service.create_interviewer(InterviewerCreate(name="钱面试官", email="qian@test.com"))
    resume = _create_resume(db_session)

    tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
    iv_start = tomorrow.replace(hour=9, minute=0, second=0, microsecond=0)
    iv_end = tomorrow.replace(hour=12, minute=0, second=0, microsecond=0)

    service.add_availability(AvailabilityCreate(
        interviewer_id=iv.id, start_time=iv_start, end_time=iv_end,
    ))

    # Book an interview 10:00–11:00
    interview_start = tomorrow.replace(hour=10, minute=0, second=0, microsecond=0)
    interview_end = tomorrow.replace(hour=11, minute=0, second=0, microsecond=0)
    service.create_interview(InterviewCreate(
        resume_id=resume.id,
        interviewer_id=iv.id,
        start_time=interview_start,
        end_time=interview_end,
    ))

    # Candidate available 9:00–12:00
    slots = service.match_slots(
        interviewer_id=iv.id,
        candidate_slots=[CandidateAvailability(start_time=iv_start, end_time=iv_end)],
        duration_minutes=60,
    )
    # Slots that conflict with 10:00–11:00 should be excluded
    iv_start_naive = interview_start.replace(tzinfo=None)
    iv_end_naive = interview_end.replace(tzinfo=None)
    for slot in slots:
        assert not (slot["start_time"] < iv_end_naive and slot["end_time"] > iv_start_naive)


def test_create_interview(db_session):
    service = SchedulingService(db_session)
    iv = service.create_interviewer(InterviewerCreate(name="孙面试官", email="sun@test.com"))
    resume = _create_resume(db_session)

    tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
    start = tomorrow.replace(hour=14, minute=0, second=0, microsecond=0)
    end = tomorrow.replace(hour=15, minute=0, second=0, microsecond=0)

    interview = service.create_interview(InterviewCreate(
        resume_id=resume.id,
        interviewer_id=iv.id,
        start_time=start,
        end_time=end,
    ))
    assert interview is not None
    assert interview.id is not None
    assert interview.status == "scheduled"


def test_create_interview_conflict(db_session):
    service = SchedulingService(db_session)
    iv = service.create_interviewer(InterviewerCreate(name="周面试官", email="zhou@test.com"))
    resume = _create_resume(db_session)

    tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
    start = tomorrow.replace(hour=14, minute=0, second=0, microsecond=0)
    end = tomorrow.replace(hour=15, minute=0, second=0, microsecond=0)

    service.create_interview(InterviewCreate(
        resume_id=resume.id, interviewer_id=iv.id, start_time=start, end_time=end,
    ))

    # Overlapping interview should return None
    conflict = service.create_interview(InterviewCreate(
        resume_id=resume.id, interviewer_id=iv.id,
        start_time=start + timedelta(minutes=30),
        end_time=end + timedelta(minutes=30),
    ))
    assert conflict is None


def test_cancel_interview(db_session):
    service = SchedulingService(db_session)
    iv = service.create_interviewer(InterviewerCreate(name="吴面试官", email="wu@test.com"))
    resume = _create_resume(db_session)

    tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
    start = tomorrow.replace(hour=16, minute=0, second=0, microsecond=0)
    end = tomorrow.replace(hour=17, minute=0, second=0, microsecond=0)

    interview = service.create_interview(InterviewCreate(
        resume_id=resume.id, interviewer_id=iv.id, start_time=start, end_time=end,
    ))
    cancelled = service.cancel_interview(interview.id)
    assert cancelled.status == "cancelled"
