"""spec 0429 阶段 C — 强制 IntakeCandidate ⇄ Resume 1:1

Revision ID: 0023
Revises: 0022
Create Date: 2026-04-29

策略:
  1. resumes 加 intake_candidate_id 列 (FK + UNIQUE WHERE NOT NULL)
  2. 回填: 每个 Resume 反向匹配 promoted_resume_id 找到对应 candidate
  3. intake_candidates.promoted_resume_id 加 partial unique index
  4. 应用层在 promote_to_resume / 手动上传 / F3 路径全部维护这个反向键

孤儿处理:
  - 老 Resume 行无对应 IntakeCandidate (F3/手动上传 Stage B 之前)
  - 让其 intake_candidate_id 保持 NULL；UNIQUE WHERE NOT NULL 不阻塞
  - 后续可跑 backfill 补建 candidate (本 migration 不做, 避免数据风险)

回滚:
  - 删 partial unique indexes + intake_candidate_id 列
"""
from alembic import op
import sqlalchemy as sa


revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # 1. resumes 加 intake_candidate_id 列
    resume_cols = {c["name"] for c in insp.get_columns("resumes")}
    if "intake_candidate_id" not in resume_cols:
        op.add_column(
            "resumes",
            sa.Column("intake_candidate_id", sa.Integer(), nullable=True),
        )

    # 2. 回填反向键（每个 Resume 找指它的 candidate）
    bind.execute(sa.text("""
        UPDATE resumes
        SET intake_candidate_id = (
            SELECT c.id FROM intake_candidates c
            WHERE c.promoted_resume_id = resumes.id
            LIMIT 1
        )
        WHERE intake_candidate_id IS NULL
    """))

    # 3. 反向键 partial unique index
    existing_idx = {ix["name"] for ix in insp.get_indexes("resumes")}
    if "uniq_resumes_intake_candidate_id" not in existing_idx:
        # SQLite 支持 partial index via raw SQL
        bind.execute(sa.text(
            "CREATE UNIQUE INDEX uniq_resumes_intake_candidate_id "
            "ON resumes(intake_candidate_id) WHERE intake_candidate_id IS NOT NULL"
        ))

    # 4. promoted_resume_id partial unique
    existing_idx_intake = {ix["name"] for ix in insp.get_indexes("intake_candidates")}
    if "uniq_intake_candidates_promoted_resume_id" not in existing_idx_intake:
        bind.execute(sa.text(
            "CREATE UNIQUE INDEX uniq_intake_candidates_promoted_resume_id "
            "ON intake_candidates(promoted_resume_id) "
            "WHERE promoted_resume_id IS NOT NULL"
        ))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("DROP INDEX IF EXISTS uniq_intake_candidates_promoted_resume_id"))
    bind.execute(sa.text("DROP INDEX IF EXISTS uniq_resumes_intake_candidate_id"))
    op.drop_column("resumes", "intake_candidate_id")
