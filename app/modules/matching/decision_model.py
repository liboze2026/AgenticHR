"""spec 0429-D — 岗位 × 候选人 人工决策表 (passed/rejected)。

candidate × job 维度独立。passed → 进约面试候选人下拉; rejected → 排除; 无行 → 未决。
"""
from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)

from app.database import Base


class JobCandidateDecision(Base):
    __tablename__ = "job_candidate_decisions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    job_id = Column(
        Integer, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    candidate_id = Column(
        Integer,
        ForeignKey("intake_candidates.id", ondelete="CASCADE"),
        nullable=False,
    )
    action = Column(String(20), nullable=False)
    decided_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("job_id", "candidate_id", name="uq_jcd_job_candidate"),
        CheckConstraint(
            "action IN ('passed','rejected')", name="ck_jcd_action_enum"
        ),
        Index("ix_jcd_user_id", "user_id"),
        Index("ix_jcd_job_id", "job_id"),
        Index("ix_jcd_candidate_id", "candidate_id"),
    )
