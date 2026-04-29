"""merge resume fields into intake_candidates + add school_tier_min on jobs

Revision ID: 0020
Revises: 0019
Create Date: 2026-04-28
"""
from alembic import op
import sqlalchemy as sa


revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


_NEW_INTAKE_COLUMNS = [
    ("phone", sa.String(20), ""),
    ("email", sa.String(200), ""),
    ("education", sa.String(50), ""),
    ("bachelor_school", sa.String(200), ""),
    ("master_school", sa.String(200), ""),
    ("phd_school", sa.String(200), ""),
    ("school_tier", sa.String(20), ""),
    ("work_years", sa.Integer(), 0),
    ("skills", sa.Text(), ""),
    ("work_experience", sa.Text(), ""),
    ("project_experience", sa.Text(), ""),
    ("self_evaluation", sa.Text(), ""),
    ("seniority", sa.String(20), ""),
    ("expected_salary_min", sa.Float(), 0),
    ("expected_salary_max", sa.Float(), 0),
    ("qr_code_path", sa.String(500), ""),
    ("ai_parsed", sa.String(10), "no"),
    ("ai_summary", sa.Text(), ""),
    ("ai_score", sa.Float(), None),
    ("greet_status", sa.String(20), "none"),
    ("greeted_at", sa.DateTime(), None),
]


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    existing_intake = {c["name"] for c in insp.get_columns("intake_candidates")}
    for col_name, col_type, default in _NEW_INTAKE_COLUMNS:
        if col_name in existing_intake:
            continue
        if default is None:
            op.add_column(
                "intake_candidates",
                sa.Column(col_name, col_type, nullable=True),
            )
        else:
            op.add_column(
                "intake_candidates",
                sa.Column(
                    col_name,
                    col_type,
                    nullable=False,
                    server_default=sa.text(repr(default)) if isinstance(default, str) else sa.text(str(default)),
                ),
            )

    existing_jobs = {c["name"] for c in insp.get_columns("jobs")}
    if "school_tier_min" not in existing_jobs:
        op.add_column(
            "jobs",
            sa.Column(
                "school_tier_min",
                sa.String(20),
                nullable=False,
                server_default="",
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    existing_jobs = {c["name"] for c in insp.get_columns("jobs")}
    if "school_tier_min" in existing_jobs:
        op.drop_column("jobs", "school_tier_min")

    existing_intake = {c["name"] for c in insp.get_columns("intake_candidates")}
    for col_name, _t, _d in reversed(_NEW_INTAKE_COLUMNS):
        if col_name in existing_intake:
            op.drop_column("intake_candidates", col_name)
