"""Add phrase_timestamps to intake_slots

Revision ID: 0015
Revises: 0014
Create Date: 2026-04-23

Stores per-phrase message timestamps for slot values that span multiple messages.
Format: [{text: str, sent_at: str | null}]
"""
from alembic import op
import sqlalchemy as sa

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("intake_slots") as batch:
        batch.add_column(sa.Column("phrase_timestamps", sa.JSON, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("intake_slots") as batch:
        batch.drop_column("phrase_timestamps")
