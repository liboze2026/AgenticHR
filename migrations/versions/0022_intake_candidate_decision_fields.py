"""spec 0429 阶段 A — IntakeCandidate 加 status / reject_reason + 回填

Revision ID: 0022
Revises: 0021
Create Date: 2026-04-29

策略:
  IntakeCandidate 加 status (pending/passed/rejected) + reject_reason 列。
  从 promoted Resume 回填；无 promoted 的按 intake_status 推导。
  阶段 A 仅加列，不动 Resume.status 写入路径（双写过渡期由应用层保证一致）。
"""
from alembic import op
import sqlalchemy as sa


revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    cols = {c["name"] for c in insp.get_columns("intake_candidates")}
    if "status" not in cols:
        op.add_column(
            "intake_candidates",
            sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        )
    if "reject_reason" not in cols:
        op.add_column(
            "intake_candidates",
            sa.Column("reject_reason", sa.String(200), nullable=False, server_default=""),
        )

    # 回填 status：promoted Resume 的 status 优先；无 promoted 按 intake_status 推
    bind.execute(sa.text("""
        UPDATE intake_candidates
        SET status = COALESCE(
            (SELECT r.status FROM resumes r WHERE r.id = intake_candidates.promoted_resume_id),
            CASE intake_candidates.intake_status
                WHEN 'complete'  THEN 'passed'
                WHEN 'abandoned' THEN 'rejected'
                WHEN 'timed_out' THEN 'rejected'
                ELSE 'pending'
            END
        )
        WHERE 1=1
    """))

    # 回填 reject_reason：仅从 promoted Resume 拉
    bind.execute(sa.text("""
        UPDATE intake_candidates
        SET reject_reason = COALESCE(
            (SELECT r.reject_reason FROM resumes r WHERE r.id = intake_candidates.promoted_resume_id),
            ''
        )
        WHERE promoted_resume_id IS NOT NULL
    """))


def downgrade() -> None:
    op.drop_column("intake_candidates", "reject_reason")
    op.drop_column("intake_candidates", "status")
