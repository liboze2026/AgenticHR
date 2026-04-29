"""spec 0429-D — 岗位 × 候选人 人工决策表

Revision ID: 0024
Revises: 0023
Create Date: 2026-04-29

策略:
  1. 建 job_candidate_decisions 表
  2. 回填: 把 matching_results.job_action != NULL 的人工决策迁过来
     (按 resume_id → intake_candidates.promoted_resume_id 反查 candidate_id)
  3. 冲突 INSERT OR IGNORE (UNIQUE job_id+candidate_id 已有就跳过)

回滚:
  - drop table; matching_results.job_action 字段未删, 五维 Tab 本地排序仍可工作
"""
from alembic import op
import sqlalchemy as sa


revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if "job_candidate_decisions" not in insp.get_table_names():
        op.create_table(
            "job_candidate_decisions",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column(
                "user_id",
                sa.Integer,
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "job_id",
                sa.Integer,
                sa.ForeignKey("jobs.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "candidate_id",
                sa.Integer,
                sa.ForeignKey("intake_candidates.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("action", sa.String(20), nullable=False),
            sa.Column(
                "decided_at",
                sa.DateTime,
                nullable=False,
                server_default=sa.func.current_timestamp(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime,
                nullable=False,
                server_default=sa.func.current_timestamp(),
            ),
            sa.UniqueConstraint(
                "job_id", "candidate_id", name="uq_jcd_job_candidate"
            ),
            sa.CheckConstraint(
                "action IN ('passed','rejected')", name="ck_jcd_action_enum"
            ),
        )
        op.create_index("ix_jcd_user_id", "job_candidate_decisions", ["user_id"])
        op.create_index("ix_jcd_job_id", "job_candidate_decisions", ["job_id"])
        op.create_index(
            "ix_jcd_candidate_id", "job_candidate_decisions", ["candidate_id"]
        )

    # 回填: matching_results.job_action != NULL → decision 表
    # SQLite 用 INSERT OR IGNORE 避 UNIQUE 冲突
    bind.execute(sa.text("""
        INSERT OR IGNORE INTO job_candidate_decisions
            (user_id, job_id, candidate_id, action, decided_at, updated_at)
        SELECT
            r.user_id, mr.job_id, c.id, mr.job_action,
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        FROM matching_results mr
        JOIN resumes r ON r.id = mr.resume_id
        JOIN intake_candidates c ON c.promoted_resume_id = mr.resume_id
        WHERE mr.job_action IN ('passed','rejected')
    """))


def downgrade() -> None:
    op.drop_index("ix_jcd_candidate_id", table_name="job_candidate_decisions")
    op.drop_index("ix_jcd_job_id", table_name="job_candidate_decisions")
    op.drop_index("ix_jcd_user_id", table_name="job_candidate_decisions")
    op.drop_table("job_candidate_decisions")
