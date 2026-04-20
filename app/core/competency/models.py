"""Skill SQLAlchemy model. Schema 由 migration 0002 建立."""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, Text, Boolean, DateTime, JSON, LargeBinary
from app.database import Base


class Skill(Base):
    __tablename__ = "skills"

    id = Column(Integer, primary_key=True, autoincrement=True)
    canonical_name = Column(Text, unique=True, nullable=False)
    aliases = Column(JSON, default=list)
    category = Column(Text, default="uncategorized")
    embedding = Column(LargeBinary, nullable=True)
    source = Column(Text, nullable=False)
    pending_classification = Column(Boolean, default=False)
    usage_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
