"""F2 匹配结果 ORM."""
from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, Float, Integer, String, Text, UniqueConstraint

from app.database import Base


class MatchingResult(Base):
    __tablename__ = "matching_results"
    __table_args__ = (
        UniqueConstraint("resume_id", "job_id", name="uq_mr_resume_job"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    resume_id = Column(Integer, nullable=False, index=True)
    job_id = Column(Integer, nullable=False)

    total_score = Column(Float, nullable=False)
    skill_score = Column(Float, nullable=False)
    experience_score = Column(Float, nullable=False)
    seniority_score = Column(Float, nullable=False)
    education_score = Column(Float, nullable=False)
    industry_score = Column(Float, nullable=False)

    hard_gate_passed = Column(Integer, nullable=False, default=1)
    missing_must_haves = Column(Text, nullable=False, default="[]")
    evidence = Column(Text, nullable=False, default="{}")
    tags = Column(Text, nullable=False, default="[]")

    competency_hash = Column(String(40), nullable=False)
    weights_hash = Column(String(40), nullable=False)

    scored_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
