from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, DateTime, JSON, ForeignKey, Index
from app.database import Base


class IntakeCandidate(Base):
    __tablename__ = "intake_candidates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    boss_id = Column(String(64), nullable=False)
    name = Column(String(128), nullable=False, default="")
    job_intention = Column(String(256), nullable=True)
    job_id = Column(Integer, ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    intake_status = Column(String(20), nullable=False, default="collecting")
    source = Column(String(32), nullable=False, default="plugin")
    pdf_path = Column(String(512), nullable=True)
    raw_text = Column(Text, nullable=True)
    chat_snapshot = Column(JSON, nullable=True)
    intake_started_at = Column(DateTime, nullable=True)
    intake_completed_at = Column(DateTime, nullable=True)
    promoted_resume_id = Column(Integer, ForeignKey("resumes.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_intake_candidates_boss_id", "boss_id", unique=True),
        Index("ix_intake_candidates_status", "intake_status"),
        Index("ix_intake_candidates_job_id", "job_id"),
    )
