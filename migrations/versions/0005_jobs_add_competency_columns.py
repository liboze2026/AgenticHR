"""jobs add competency columns

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-20 11:26:07.372070

"""
from alembic import op
import sqlalchemy as sa


revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('jobs') as batch_op:
        batch_op.add_column(sa.Column('jd_text', sa.Text(), server_default='', nullable=False))
        batch_op.add_column(sa.Column('competency_model', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('competency_model_status', sa.Text(), server_default='none', nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('jobs') as batch_op:
        batch_op.drop_column('competency_model_status')
        batch_op.drop_column('competency_model')
        batch_op.drop_column('jd_text')
