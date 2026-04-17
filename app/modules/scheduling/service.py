"""面试安排业务逻辑"""
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.modules.scheduling.models import Interviewer, InterviewerAvailability, Interview
from app.modules.scheduling.schemas import (
    InterviewerCreate,
    AvailabilityCreate,
    InterviewCreate,
    InterviewUpdate,
    CandidateAvailability,
)


class SchedulingService:
    def __init__(self, db: Session):
        self.db = db

    # ── Interviewer CRUD ──

    def create_interviewer(self, data: InterviewerCreate) -> Interviewer:
        interviewer = Interviewer(**data.model_dump())
        self.db.add(interviewer)
        self.db.commit()
        self.db.refresh(interviewer)
        return interviewer

    def get_interviewer(self, interviewer_id: int) -> Interviewer | None:
        return self.db.query(Interviewer).filter(Interviewer.id == interviewer_id).first()

    def list_interviewers(self) -> dict:
        items = self.db.query(Interviewer).order_by(Interviewer.id).all()
        return {"total": len(items), "items": items}

    def delete_interviewer(self, interviewer_id: int) -> bool:
        interviewer = self.get_interviewer(interviewer_id)
        if not interviewer:
            return False
        self.db.delete(interviewer)
        self.db.commit()
        return True

    # ── Availability ──

    def add_availability(self, data: AvailabilityCreate) -> InterviewerAvailability:
        avail = InterviewerAvailability(**data.model_dump())
        self.db.add(avail)
        self.db.commit()
        self.db.refresh(avail)
        return avail

    def get_availability(self, interviewer_id: int) -> list[InterviewerAvailability]:
        return (
            self.db.query(InterviewerAvailability)
            .filter(InterviewerAvailability.interviewer_id == interviewer_id)
            .order_by(InterviewerAvailability.start_time)
            .all()
        )

    # ── Slot matching ──

    @staticmethod
    def _naive(dt: datetime) -> datetime:
        """Strip timezone info for consistent comparison (SQLite stores naive datetimes)."""
        return dt.replace(tzinfo=None) if dt.tzinfo else dt

    def match_slots(
        self,
        interviewer_id: int,
        candidate_slots: list[CandidateAvailability],
        duration_minutes: int = 60,
    ) -> list[dict]:
        """Find overlapping time slots between interviewer availability and candidate
        availability, excluding existing interviews. Returns duration-sized slots
        with 30-minute steps."""
        interviewer_avails = self.get_availability(interviewer_id)

        # Get existing scheduled interviews for this interviewer
        existing_interviews = (
            self.db.query(Interview)
            .filter(
                Interview.interviewer_id == interviewer_id,
                Interview.status != "cancelled",
            )
            .all()
        )

        duration = timedelta(minutes=duration_minutes)
        step = timedelta(minutes=30)
        result = []

        for avail in interviewer_avails:
            for cs in candidate_slots:
                # Normalize to naive datetimes for comparison
                a_start = self._naive(avail.start_time)
                a_end = self._naive(avail.end_time)
                c_start = self._naive(cs.start_time)
                c_end = self._naive(cs.end_time)

                # Find the overlap
                overlap_start = max(a_start, c_start)
                overlap_end = min(a_end, c_end)

                if overlap_end - overlap_start < duration:
                    continue

                # Slice into duration-sized slots with 30-min steps
                slot_start = overlap_start
                while slot_start + duration <= overlap_end:
                    slot_end = slot_start + duration

                    # Check against existing interviews
                    conflict = False
                    for iv in existing_interviews:
                        iv_start = self._naive(iv.start_time)
                        iv_end = self._naive(iv.end_time)
                        if slot_start < iv_end and slot_end > iv_start:
                            conflict = True
                            break

                    if not conflict:
                        result.append({
                            "start_time": slot_start,
                            "end_time": slot_end,
                        })

                    slot_start += step

        return result

    # ── Interview CRUD ──

    def create_interview(self, data: InterviewCreate, user_id: int = 0) -> Interview | None:
        """Create an interview, returning None if there is a time conflict."""
        conflict = (
            self.db.query(Interview)
            .filter(
                Interview.interviewer_id == data.interviewer_id,
                Interview.status != "cancelled",
                Interview.start_time < data.end_time,
                Interview.end_time > data.start_time,
            )
            .first()
        )
        if conflict:
            return None

        interview = Interview(**data.model_dump())
        interview.user_id = user_id
        self.db.add(interview)
        self.db.commit()
        self.db.refresh(interview)
        return interview

    def get_interview(self, interview_id: int) -> Interview | None:
        return self.db.query(Interview).filter(Interview.id == interview_id).first()

    def list_interviews(
        self,
        interviewer_id: int | None = None,
        resume_id: int | None = None,
        status: str | None = None,
        user_id: int | None = None,
    ) -> dict:
        query = self.db.query(Interview)
        if user_id is not None:
            query = query.filter(Interview.user_id == user_id)
        if interviewer_id is not None:
            query = query.filter(Interview.interviewer_id == interviewer_id)
        if resume_id is not None:
            query = query.filter(Interview.resume_id == resume_id)
        if status is not None:
            query = query.filter(Interview.status == status)
        # 最新创建的排在最上面，方便用户刚新建完立即看到
        items = query.order_by(Interview.created_at.desc()).all()
        return {"total": len(items), "items": items}

    def update_interview(self, interview_id: int, data: InterviewUpdate) -> Interview | None:
        interview = self.get_interview(interview_id)
        if not interview:
            return None
        update_data = data.model_dump(exclude_none=True)
        for key, value in update_data.items():
            setattr(interview, key, value)
        self.db.commit()
        self.db.refresh(interview)
        return interview

    def cancel_interview(self, interview_id: int) -> Interview | None:
        interview = self.get_interview(interview_id)
        if not interview:
            return None
        interview.status = "cancelled"
        self.db.commit()
        self.db.refresh(interview)
        return interview
