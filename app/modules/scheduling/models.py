"""面试官与面试安排数据模型"""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey

from app.database import Base


class Interviewer(Base):
    __tablename__ = "interviewers"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    phone = Column(String(20), default="")
    feishu_user_id = Column(String(100), default="")
    email = Column(String(200), default="")
    department = Column(String(100), default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


class InterviewerAvailability(Base):
    __tablename__ = "interviewer_availability"
    id = Column(Integer, primary_key=True, autoincrement=True)
    interviewer_id = Column(Integer, ForeignKey("interviewers.id"), nullable=False)
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=False)
    source = Column(String(50), default="manual")


class Interview(Base):
    __tablename__ = "interviews"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, default=0, index=True)
    resume_id = Column(Integer, ForeignKey("resumes.id"), nullable=False)
    interviewer_id = Column(Integer, ForeignKey("interviewers.id"), nullable=False)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=True)
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=False)
    meeting_topic = Column(String(200), default="")
    meeting_link = Column(String(500), default="")
    meeting_password = Column(String(100), default="")
    meeting_account = Column(String(50), default="")
    meeting_id = Column(String(50), default="")
    feishu_event_id = Column(String(200), default="")
    status = Column(String(20), default="scheduled")
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc), nullable=False,
    )
