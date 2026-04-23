"""Add batch_collect_criteria to jobs

Revision ID: 0016
Revises: 0015
Create Date: 2026-04-23
"""
from alembic import op
import sqlalchemy as sa

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("jobs") as batch:
        batch.add_column(sa.Column("batch_collect_criteria", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("jobs") as batch:
        batch.drop_column("batch_collect_criteria")
