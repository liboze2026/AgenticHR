"""F5 intake_user_settings: global target-count + pause/resume gate

Revision ID: 0018
Revises: 0017
Create Date: 2026-04-24
"""
from alembic import op
import sqlalchemy as sa

revision = '0018'
down_revision = '0017'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'intake_user_settings',
        sa.Column('user_id', sa.Integer, primary_key=True),
        sa.Column('enabled', sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column('target_count', sa.Integer, nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime, nullable=False,
                  server_default=sa.func.current_timestamp()),
        sa.Column('updated_at', sa.DateTime, nullable=False,
                  server_default=sa.func.current_timestamp()),
    )


def downgrade() -> None:
    op.drop_table('intake_user_settings')
