"""backfill IntakeCandidate from Resume + compute school_tier

Revision ID: 0021
Revises: 0020
Create Date: 2026-04-28

策略:
  对每个已 promote 的 Resume(promoted_resume_id 反向匹配), 把学校/学历/技能等
  字段同步到对应 IntakeCandidate 行(empty 才覆盖, 不覆盖已填字段)。
  跑完后回填 school_tier。
  不删除 Resume 表(保留为只读历史归档, 后续可手动 drop)。
"""
from alembic import op
import sqlalchemy as sa


revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


_RESUME_COPY_FIELDS = (
    "phone", "email", "education", "bachelor_school", "master_school",
    "phd_school", "qr_code_path", "work_years", "expected_salary_min",
    "expected_salary_max", "skills", "work_experience", "project_experience",
    "self_evaluation", "seniority", "ai_parsed", "ai_summary", "ai_score",
    "greet_status",
)


def upgrade() -> None:
    bind = op.get_bind()

    # 1. 对所有 IntakeCandidate, 若有 promoted_resume_id 则把对应 Resume 字段合并过来。
    rows = bind.execute(sa.text(
        "SELECT id, promoted_resume_id FROM intake_candidates "
        "WHERE promoted_resume_id IS NOT NULL"
    )).fetchall()

    for cand_id, resume_id in rows:
        if not resume_id:
            continue
        # 取 Resume 行
        r = bind.execute(sa.text(
            "SELECT phone, email, education, bachelor_school, master_school, "
            "phd_school, qr_code_path, work_years, expected_salary_min, "
            "expected_salary_max, skills, work_experience, project_experience, "
            "self_evaluation, seniority, ai_parsed, ai_summary, ai_score, greet_status "
            "FROM resumes WHERE id = :rid"
        ), {"rid": resume_id}).fetchone()
        if not r:
            continue

        # 取当前 IntakeCandidate 字段(用于不覆盖判断)
        c = bind.execute(sa.text(
            "SELECT phone, email, education, bachelor_school, master_school, "
            "phd_school, qr_code_path, work_years, expected_salary_min, "
            "expected_salary_max, skills, work_experience, project_experience, "
            "self_evaluation, seniority, ai_parsed, ai_summary, ai_score, greet_status "
            "FROM intake_candidates WHERE id = :cid"
        ), {"cid": cand_id}).fetchone()
        if not c:
            continue

        updates: dict = {}
        for i, col in enumerate(_RESUME_COPY_FIELDS):
            cand_val = c[i]
            res_val = r[i]
            if res_val in (None, "", 0):
                continue
            if cand_val in (None, "", 0):
                updates[col] = res_val

        if updates:
            set_clause = ", ".join(f"{k} = :{k}" for k in updates)
            updates["cid"] = cand_id
            bind.execute(sa.text(
                f"UPDATE intake_candidates SET {set_clause} WHERE id = :cid"
            ), updates)

    # 2. 回填 school_tier(基于 bachelor_school/master_school/phd_school)
    from app.modules.im_intake.school_tier import classify_school

    cand_rows = bind.execute(sa.text(
        "SELECT id, phd_school, master_school, bachelor_school, school_tier "
        "FROM intake_candidates"
    )).fetchall()

    for row in cand_rows:
        cid, phd, mas, bac, current_tier = row
        if current_tier:
            continue
        for sch in (phd, mas, bac):
            if not sch:
                continue
            t = classify_school(sch)
            if t:
                bind.execute(sa.text(
                    "UPDATE intake_candidates SET school_tier = :t WHERE id = :cid"
                ), {"t": t, "cid": cid})
                break


def downgrade() -> None:
    # 回填型 migration; 无逆操作(数据迁移不应反向执行)
    pass
