"""add f2 matching_results and resumes.seniority

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-20

"""
from alembic import op
import sqlalchemy as sa


revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'matching_results',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('resume_id', sa.Integer, nullable=False),
        sa.Column('job_id', sa.Integer, nullable=False),
        sa.Column('total_score', sa.Float, nullable=False),
        sa.Column('skill_score', sa.Float, nullable=False),
        sa.Column('experience_score', sa.Float, nullable=False),
        sa.Column('seniority_score', sa.Float, nullable=False),
        sa.Column('education_score', sa.Float, nullable=False),
        sa.Column('industry_score', sa.Float, nullable=False),
        sa.Column('hard_gate_passed', sa.Integer, nullable=False, server_default='1'),
        sa.Column('missing_must_haves', sa.Text, nullable=False, server_default='[]'),
        sa.Column('evidence', sa.Text, nullable=False, server_default='{}'),
        sa.Column('tags', sa.Text, nullable=False, server_default='[]'),
        sa.Column('competency_hash', sa.String(40), nullable=False),
        sa.Column('weights_hash', sa.String(40), nullable=False),
        sa.Column('scored_at', sa.DateTime, nullable=False),
        sa.UniqueConstraint('resume_id', 'job_id', name='uq_mr_resume_job'),
    )
    op.create_index('idx_mr_job_score', 'matching_results',
                    ['job_id', sa.text('total_score DESC')])
    op.create_index('idx_mr_resume', 'matching_results', ['resume_id'])

    with op.batch_alter_table('resumes') as batch_op:
        batch_op.add_column(
            sa.Column('seniority', sa.String(20), nullable=False, server_default='')
        )


def downgrade() -> None:
    with op.batch_alter_table('resumes') as batch_op:
        batch_op.drop_column('seniority')

    op.drop_index('idx_mr_resume', 'matching_results')
    op.drop_index('idx_mr_job_score', 'matching_results')
    op.drop_table('matching_results')
