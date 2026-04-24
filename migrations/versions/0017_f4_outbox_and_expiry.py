"""F4 outbox + intake_candidates.expires_at

Revision ID: 0017
Revises: 0016
Create Date: 2026-04-24
"""
from alembic import op
import sqlalchemy as sa

revision = '0017'
down_revision = '0016'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'intake_outbox',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('candidate_id', sa.Integer, nullable=False),
        sa.Column('user_id', sa.Integer, nullable=False, server_default='0'),
        sa.Column('action_type', sa.String(32), nullable=False),
        sa.Column('text', sa.Text, nullable=False, server_default=''),
        sa.Column('slot_keys', sa.JSON, nullable=True),
        sa.Column('status', sa.String(16), nullable=False, server_default='pending'),
        sa.Column('scheduled_for', sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column('claimed_at', sa.DateTime, nullable=True),
        sa.Column('sent_at', sa.DateTime, nullable=True),
        sa.Column('attempts', sa.Integer, nullable=False, server_default='0'),
        sa.Column('last_error', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()),
        sa.ForeignKeyConstraint(['candidate_id'], ['intake_candidates.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_intake_outbox_status_scheduled', 'intake_outbox', ['status', 'scheduled_for'])
    op.create_index('ix_intake_outbox_user_status', 'intake_outbox', ['user_id', 'status'])
    op.create_index('ix_intake_outbox_candidate_status', 'intake_outbox', ['candidate_id', 'status'])

    with op.batch_alter_table('intake_candidates') as batch_op:
        batch_op.add_column(sa.Column('expires_at', sa.DateTime, nullable=True))
        batch_op.create_index('ix_intake_candidates_expires_at', ['expires_at'])


def downgrade() -> None:
    with op.batch_alter_table('intake_candidates') as batch_op:
        batch_op.drop_index('ix_intake_candidates_expires_at')
        batch_op.drop_column('expires_at')
    op.drop_index('ix_intake_outbox_candidate_status', table_name='intake_outbox')
    op.drop_index('ix_intake_outbox_user_status', table_name='intake_outbox')
    op.drop_index('ix_intake_outbox_status_scheduled', table_name='intake_outbox')
    op.drop_table('intake_outbox')
