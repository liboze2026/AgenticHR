"""create skills table

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-20 11:18:38.752942

"""
from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'skills',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('canonical_name', sa.Text(), nullable=False),
        sa.Column('aliases', sa.JSON(), server_default='[]', nullable=False),
        sa.Column('category', sa.Text(), server_default='uncategorized', nullable=False),
        sa.Column('embedding', sa.LargeBinary(), nullable=True),
        sa.Column('source', sa.Text(), nullable=False),
        sa.Column('pending_classification', sa.Boolean(), server_default=sa.text('0'), nullable=False),
        sa.Column('usage_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('canonical_name'),
    )
    op.create_index('idx_skills_category', 'skills', ['category'])
    op.create_index(
        'idx_skills_pending', 'skills', ['pending_classification'],
        sqlite_where=sa.text('pending_classification = 1'),
    )


def downgrade() -> None:
    op.drop_index('idx_skills_pending', 'skills')
    op.drop_index('idx_skills_category', 'skills')
    op.drop_table('skills')
