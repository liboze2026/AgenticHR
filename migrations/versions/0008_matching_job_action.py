"""add matching_results.job_action

Revision ID: 0008
Revises: 0007
Create Date: 2026-04-21
"""
from alembic import op
import sqlalchemy as sa

revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('matching_results') as batch_op:
        batch_op.add_column(sa.Column('job_action', sa.String(20), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('matching_results') as batch_op:
        batch_op.drop_column('job_action')
