"""F3 recruit_bot fields: users.daily_cap, jobs.greet_threshold, resumes.{boss_id, greet_status, greeted_at} + UNIQUE(user_id, boss_id)

Revision ID: 0010
Revises: 0009
Create Date: 2026-04-21
"""
from alembic import op
import sqlalchemy as sa

revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('users') as batch_op:
        batch_op.add_column(
            sa.Column('daily_cap', sa.Integer(), server_default='1000', nullable=False)
        )

    with op.batch_alter_table('jobs') as batch_op:
        batch_op.add_column(
            sa.Column('greet_threshold', sa.Integer(), server_default='60', nullable=False)
        )

    with op.batch_alter_table('resumes') as batch_op:
        batch_op.add_column(
            sa.Column('boss_id', sa.String(100), server_default='', nullable=False)
        )
        batch_op.add_column(
            sa.Column('greet_status', sa.String(20), server_default='none', nullable=False)
        )
        batch_op.add_column(
            sa.Column('greeted_at', sa.DateTime(), nullable=True)
        )
        batch_op.create_index('ix_resumes_boss_id', ['boss_id'])

    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_resumes_user_boss "
        "ON resumes(user_id, boss_id) WHERE boss_id != ''"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_resumes_user_boss")

    with op.batch_alter_table('resumes') as batch_op:
        batch_op.drop_index('ix_resumes_boss_id')
        batch_op.drop_column('greeted_at')
        batch_op.drop_column('greet_status')
        batch_op.drop_column('boss_id')

    with op.batch_alter_table('jobs') as batch_op:
        batch_op.drop_column('greet_threshold')

    with op.batch_alter_table('users') as batch_op:
        batch_op.drop_column('daily_cap')
