"""add last_checked_at to intake_candidates

Revision ID: 0019
Revises: 0018
Create Date: 2026-04-26
"""
from alembic import op
import sqlalchemy as sa

revision = '0019'
down_revision = '0018'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('intake_candidates',
                  sa.Column('last_checked_at', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('intake_candidates', 'last_checked_at')
