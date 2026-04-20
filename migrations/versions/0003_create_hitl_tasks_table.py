"""create hitl_tasks table

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-20 11:24:26.423165

"""
from alembic import op
import sqlalchemy as sa


revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'hitl_tasks',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('f_stage', sa.Text(), nullable=False),
        sa.Column('entity_type', sa.Text(), nullable=False),
        sa.Column('entity_id', sa.Integer(), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('status', sa.Text(), server_default='pending', nullable=False),
        sa.Column('edited_payload', sa.JSON(), nullable=True),
        sa.Column('reviewer_id', sa.Integer(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_hitl_status', 'hitl_tasks', ['status'])
    op.create_index('idx_hitl_stage', 'hitl_tasks', ['f_stage', 'status'])


def downgrade() -> None:
    op.drop_index('idx_hitl_stage', 'hitl_tasks')
    op.drop_index('idx_hitl_status', 'hitl_tasks')
    op.drop_table('hitl_tasks')
