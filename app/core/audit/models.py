"""audit_events SQLAlchemy model. Schema 由 migration 0004 建立."""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, Text, DateTime
from app.database import Base


class AuditEvent(Base):
    __tablename__ = "audit_events"

    event_id = Column(Text, primary_key=True)
    f_stage = Column(Text, nullable=False)
    action = Column(Text, nullable=False)
    entity_type = Column(Text, nullable=False)
    entity_id = Column(Integer, nullable=True)
    input_hash = Column(Text, nullable=True)
    output_hash = Column(Text, nullable=True)
    prompt_version = Column(Text, nullable=True)
    model_name = Column(Text, nullable=True)
    model_version = Column(Text, nullable=True)
    reviewer_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    retention_until = Column(DateTime, nullable=True)
