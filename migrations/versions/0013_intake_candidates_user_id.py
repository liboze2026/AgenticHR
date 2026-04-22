"""F5: add user_id to intake_candidates for multi-tenancy

Revision ID: 0013
Revises: 0012
Create Date: 2026-04-22

- Adds user_id (NOT NULL, default 0 for legacy rows) with FK to users(id) ondelete CASCADE.
- Replaces UNIQUE(boss_id) with UNIQUE(user_id, boss_id) so different users can
  independently track candidates that happen to share a Boss IM id.
- Adds ix_intake_candidates_user_id for per-user list queries.
"""
from alembic import op
import sqlalchemy as sa

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("intake_candidates") as batch:
        batch.add_column(sa.Column(
            "user_id", sa.Integer, nullable=False, server_default="0",
        ))

    # Swap the boss_id unique index for a composite (user_id, boss_id) unique
    # index and add a standalone user_id index for list queries.
    op.drop_index("ix_intake_candidates_boss_id", table_name="intake_candidates")
    op.create_index(
        "ix_intake_candidates_user_boss", "intake_candidates",
        ["user_id", "boss_id"], unique=True,
    )
    op.create_index(
        "ix_intake_candidates_boss_id", "intake_candidates", ["boss_id"], unique=False,
    )
    op.create_index(
        "ix_intake_candidates_user_id", "intake_candidates", ["user_id"], unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_intake_candidates_user_id", table_name="intake_candidates")
    op.drop_index("ix_intake_candidates_boss_id", table_name="intake_candidates")
    op.drop_index("ix_intake_candidates_user_boss", table_name="intake_candidates")
    op.create_index(
        "ix_intake_candidates_boss_id", "intake_candidates", ["boss_id"], unique=True,
    )
    with op.batch_alter_table("intake_candidates") as batch:
        batch.drop_column("user_id")
