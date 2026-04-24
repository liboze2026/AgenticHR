"""F5 per-user intake automation settings.

One row per user_id. `enabled` = master switch (start/pause).
`target_count` = desired number of `complete` candidates; once reached,
scheduler + autoscan + outbox claim all gate off until HR changes target
or resets counts.
"""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, Boolean, DateTime
from app.database import Base


class IntakeUserSettings(Base):
    __tablename__ = "intake_user_settings"

    user_id = Column(Integer, primary_key=True)
    enabled = Column(Boolean, nullable=False, default=False)
    target_count = Column(Integer, nullable=False, default=0)
    created_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
