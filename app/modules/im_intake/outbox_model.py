from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, DateTime, JSON, ForeignKey, Index
from app.database import Base


class IntakeOutbox(Base):
    __tablename__ = "intake_outbox"

    id = Column(Integer, primary_key=True, autoincrement=True)
    candidate_id = Column(Integer, ForeignKey("intake_candidates.id", ondelete="CASCADE"),
                          nullable=False)
    user_id = Column(Integer, nullable=False, default=0)
    action_type = Column(String(32), nullable=False)
    text = Column(Text, nullable=False, default="")
    slot_keys = Column(JSON, nullable=True)
    status = Column(String(16), nullable=False, default="pending")
    scheduled_for = Column(DateTime, nullable=False,
                           default=lambda: datetime.now(timezone.utc))
    claimed_at = Column(DateTime, nullable=True)
    sent_at = Column(DateTime, nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (
        Index("ix_intake_outbox_status_scheduled", "status", "scheduled_for"),
        Index("ix_intake_outbox_user_status", "user_id", "status"),
        Index("ix_intake_outbox_candidate_status", "candidate_id", "status"),
    )
