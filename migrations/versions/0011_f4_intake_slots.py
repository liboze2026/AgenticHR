"""F4 intake_slots table + resumes.intake_* fields

Revision ID: 0011
Revises: 0010
Create Date: 2026-04-22
"""
from alembic import op
import sqlalchemy as sa

revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'intake_slots',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('resume_id', sa.Integer, nullable=False),
        sa.Column('slot_key', sa.String(64), nullable=False),
        sa.Column('slot_category', sa.String(16), nullable=False),
        sa.Column('value', sa.Text, nullable=True),
        sa.Column('asked_at', sa.DateTime, nullable=True),
        sa.Column('answered_at', sa.DateTime, nullable=True),
        sa.Column('ask_count', sa.Integer, nullable=False, server_default='0'),
        sa.Column('last_ask_text', sa.Text, nullable=True),
        sa.Column('source', sa.String(32), nullable=True),
        sa.Column('question_meta', sa.JSON, nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column('updated_at', sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()),
        sa.ForeignKeyConstraint(['resume_id'], ['resumes.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_intake_slots_resume_slot', 'intake_slots', ['resume_id', 'slot_key'], unique=True)
    op.create_index('ix_intake_slots_resume_id', 'intake_slots', ['resume_id'])
    op.create_index('ix_intake_slots_answered_at', 'intake_slots', ['answered_at'])

    with op.batch_alter_table('resumes') as batch_op:
        batch_op.add_column(sa.Column('intake_status', sa.String(20), nullable=False, server_default='collecting'))
        batch_op.add_column(sa.Column('intake_started_at', sa.DateTime, nullable=True))
        batch_op.add_column(sa.Column('intake_completed_at', sa.DateTime, nullable=True))
        batch_op.add_column(sa.Column('job_id', sa.Integer, nullable=True))
        batch_op.create_foreign_key('fk_resumes_job_id', 'jobs', ['job_id'], ['id'], ondelete='SET NULL')
        batch_op.create_index('ix_resumes_job_id', ['job_id'])


def downgrade() -> None:
    with op.batch_alter_table('resumes') as batch_op:
        batch_op.drop_index('ix_resumes_job_id')
        batch_op.drop_constraint('fk_resumes_job_id', type_='foreignkey')
        batch_op.drop_column('job_id')
        batch_op.drop_column('intake_completed_at')
        batch_op.drop_column('intake_started_at')
        batch_op.drop_column('intake_status')
    op.drop_index('ix_intake_slots_answered_at', table_name='intake_slots')
    op.drop_index('ix_intake_slots_resume_id', table_name='intake_slots')
    op.drop_index('ix_intake_slots_resume_slot', table_name='intake_slots')
    op.drop_table('intake_slots')
