"""create audit_events table with WORM triggers

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-20 11:25:22.138776

"""
from alembic import op
import sqlalchemy as sa


revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'audit_events',
        sa.Column('event_id', sa.Text(), nullable=False),
        sa.Column('f_stage', sa.Text(), nullable=False),
        sa.Column('action', sa.Text(), nullable=False),
        sa.Column('entity_type', sa.Text(), nullable=False),
        sa.Column('entity_id', sa.Integer(), nullable=True),
        sa.Column('input_hash', sa.Text(), nullable=True),
        sa.Column('output_hash', sa.Text(), nullable=True),
        sa.Column('prompt_version', sa.Text(), nullable=True),
        sa.Column('model_name', sa.Text(), nullable=True),
        sa.Column('model_version', sa.Text(), nullable=True),
        sa.Column('reviewer_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('retention_until', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('event_id'),
    )
    op.create_index('idx_audit_entity', 'audit_events', ['entity_type', 'entity_id'])
    op.create_index('idx_audit_stage', 'audit_events', ['f_stage', 'created_at'])

    op.execute("""
        CREATE TRIGGER audit_no_update
        BEFORE UPDATE ON audit_events
        FOR EACH ROW
        BEGIN
            SELECT RAISE(FAIL, 'WORM: audit_events is append-only');
        END
    """)
    op.execute("""
        CREATE TRIGGER audit_no_delete
        BEFORE DELETE ON audit_events
        FOR EACH ROW
        BEGIN
            SELECT RAISE(FAIL, 'WORM: audit_events is append-only');
        END
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_no_delete")
    op.execute("DROP TRIGGER IF EXISTS audit_no_update")
    op.drop_index('idx_audit_stage', 'audit_events')
    op.drop_index('idx_audit_entity', 'audit_events')
    op.drop_table('audit_events')
