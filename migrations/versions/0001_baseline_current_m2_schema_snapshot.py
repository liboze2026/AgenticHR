"""baseline: current M2 schema snapshot

Revision ID: 0001
Revises:
Create Date: 2026-04-20 11:10:27.370963
"""
from alembic import op
import sqlalchemy as sa

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Baseline — no-op. 代表 M2 结束时的 schema。"""
    pass


def downgrade() -> None:
    """Baseline 不可降级。"""
    pass
