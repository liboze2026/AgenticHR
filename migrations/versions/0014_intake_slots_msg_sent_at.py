"""Add msg_sent_at to intake_slots

Revision ID: 0014
Revises: 0013
Create Date: 2026-04-23

Records the send timestamp of the candidate message from which a slot value was extracted.
"""
from alembic import op
import sqlalchemy as sa

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("intake_slots") as batch:
        batch.add_column(sa.Column("msg_sent_at", sa.DateTime, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("intake_slots") as batch:
        batch.drop_column("msg_sent_at")
