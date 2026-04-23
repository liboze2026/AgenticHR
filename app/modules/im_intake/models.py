from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, DateTime, JSON, ForeignKey
from app.database import Base


class IntakeSlot(Base):
    __tablename__ = "intake_slots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    candidate_id = Column(Integer, ForeignKey("intake_candidates.id", ondelete="CASCADE"), nullable=False)
    slot_key = Column(String(64), nullable=False)
    slot_category = Column(String(16), nullable=False)
    value = Column(Text, nullable=True)
    asked_at = Column(DateTime, nullable=True)
    answered_at = Column(DateTime, nullable=True)
    ask_count = Column(Integer, nullable=False, default=0)
    last_ask_text = Column(Text, nullable=True)
    source = Column(String(32), nullable=True)
    question_meta = Column(JSON, nullable=True)
    msg_sent_at = Column(DateTime, nullable=True)
    phrase_timestamps = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
