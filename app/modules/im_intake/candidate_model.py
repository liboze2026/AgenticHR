from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, Float, DateTime, JSON, ForeignKey, Index
from app.database import Base


class IntakeCandidate(Base):
    __tablename__ = "intake_candidates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, default=0)
    boss_id = Column(String(64), nullable=False)
    name = Column(String(128), nullable=False, default="")
    phone = Column(String(20), nullable=False, default="")
    email = Column(String(200), nullable=False, default="")
    job_intention = Column(String(256), nullable=True)
    job_id = Column(Integer, ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    intake_status = Column(String(20), nullable=False, default="collecting")
    # spec 0429 阶段 A：决策字段从 Resume 下沉到 candidate，消跨表反查
    status = Column(String(20), nullable=False, default="pending")
    reject_reason = Column(String(200), nullable=False, default="")
    source = Column(String(32), nullable=False, default="plugin")
    pdf_path = Column(String(512), nullable=True)
    raw_text = Column(Text, nullable=True)
    chat_snapshot = Column(JSON, nullable=True)
    education = Column(String(50), nullable=False, default="")
    bachelor_school = Column(String(200), nullable=False, default="")
    master_school = Column(String(200), nullable=False, default="")
    phd_school = Column(String(200), nullable=False, default="")
    school_tier = Column(String(20), nullable=False, default="")
    work_years = Column(Integer, nullable=False, default=0)
    skills = Column(Text, nullable=False, default="")
    work_experience = Column(Text, nullable=False, default="")
    project_experience = Column(Text, nullable=False, default="")
    self_evaluation = Column(Text, nullable=False, default="")
    seniority = Column(String(20), nullable=False, default="")
    expected_salary_min = Column(Float, nullable=False, default=0)
    expected_salary_max = Column(Float, nullable=False, default=0)
    qr_code_path = Column(String(500), nullable=False, default="")
    ai_parsed = Column(String(10), nullable=False, default="no")
    ai_summary = Column(Text, nullable=False, default="")
    ai_score = Column(Float, nullable=True)
    greet_status = Column(String(20), nullable=False, default="none")
    greeted_at = Column(DateTime, nullable=True)
    intake_started_at = Column(DateTime, nullable=True)
    intake_completed_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    last_checked_at = Column(DateTime, nullable=True)
    promoted_resume_id = Column(Integer, ForeignKey("resumes.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_intake_candidates_user_boss", "user_id", "boss_id", unique=True),
        Index("ix_intake_candidates_boss_id", "boss_id"),
        Index("ix_intake_candidates_user_id", "user_id"),
        Index("ix_intake_candidates_status", "intake_status"),
        Index("ix_intake_candidates_job_id", "job_id"),
        Index("ix_intake_candidates_expires_at", "expires_at"),
        # spec 0429 阶段 C: 1:1 锁; 一个 Resume 只能被一个 candidate promote
        Index(
            "uniq_intake_candidates_promoted_resume_id",
            "promoted_resume_id",
            unique=True,
            sqlite_where=Column("promoted_resume_id").isnot(None),
        ),
    )
