"""HitlTask SQLAlchemy model. Schema 由 migration 0003 建立."""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, Text, DateTime, JSON
from app.database import Base


class HitlTask(Base):
    __tablename__ = "hitl_tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    f_stage = Column(Text, nullable=False)
    entity_type = Column(Text, nullable=False)
    entity_id = Column(Integer, nullable=False)
    payload = Column(JSON, nullable=False)
    status = Column(Text, nullable=False, default="pending")
    edited_payload = Column(JSON, nullable=True)
    reviewer_id = Column(Integer, nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
