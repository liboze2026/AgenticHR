"""F5 intake_candidates table + move non-complete rows out of resumes

Revision ID: 0012
Revises: 0011
Create Date: 2026-04-22
"""
from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "intake_candidates",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("boss_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False, server_default=""),
        sa.Column("job_intention", sa.String(256), nullable=True),
        sa.Column("job_id", sa.Integer, nullable=True),
        sa.Column("intake_status", sa.String(20), nullable=False, server_default="collecting"),
        sa.Column("source", sa.String(32), nullable=False, server_default="plugin"),
        sa.Column("pdf_path", sa.String(512), nullable=True),
        sa.Column("raw_text", sa.Text, nullable=True),
        sa.Column("chat_snapshot", sa.JSON, nullable=True),
        sa.Column("intake_started_at", sa.DateTime, nullable=True),
        sa.Column("intake_completed_at", sa.DateTime, nullable=True),
        sa.Column("promoted_resume_id", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["promoted_resume_id"], ["resumes.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_intake_candidates_boss_id", "intake_candidates", ["boss_id"], unique=True)
    op.create_index("ix_intake_candidates_status", "intake_candidates", ["intake_status"])
    op.create_index("ix_intake_candidates_job_id", "intake_candidates", ["job_id"])

    with op.batch_alter_table("intake_slots") as batch:
        batch.add_column(sa.Column("candidate_id", sa.Integer, nullable=True))
        batch.create_foreign_key(
            "fk_intake_slots_candidate_id",
            "intake_candidates", ["candidate_id"], ["id"], ondelete="CASCADE",
        )
        batch.create_index("ix_intake_slots_candidate_id", ["candidate_id"])

    conn = op.get_bind()
    rows = conn.execute(sa.text(
        "SELECT id, boss_id, name, job_id, intake_status, intake_started_at, "
        "intake_completed_at, created_at, updated_at FROM resumes "
        "WHERE intake_status IS NOT NULL AND intake_status != 'complete'"
    )).fetchall()
    id_map = {}
    for r in rows:
        res = conn.execute(sa.text(
            "INSERT INTO intake_candidates "
            "(boss_id, name, job_id, intake_status, source, "
            "intake_started_at, intake_completed_at, created_at, updated_at) "
            "VALUES (:boss_id, :name, :job_id, :st, 'migration', "
            ":s_at, :c_at, COALESCE(:cr, CURRENT_TIMESTAMP), "
            "COALESCE(:up, CURRENT_TIMESTAMP))"
        ), dict(boss_id=r[1] or f"legacy_{r[0]}", name=r[2] or "", job_id=r[3],
                st=r[4], s_at=r[5], c_at=r[6], cr=r[7], up=r[8]))
        id_map[r[0]] = res.lastrowid if res.lastrowid else conn.execute(
            sa.text("SELECT last_insert_rowid()")
        ).scalar()

    for old_id, new_id in id_map.items():
        conn.execute(sa.text(
            "UPDATE intake_slots SET candidate_id = :new WHERE resume_id = :old"
        ), dict(new=new_id, old=old_id))

    if id_map:
        conn.execute(sa.text(
            "DELETE FROM resumes WHERE id IN :ids"
        ).bindparams(sa.bindparam("ids", expanding=True)), dict(ids=list(id_map.keys())))

    with op.batch_alter_table("intake_slots") as batch:
        batch.alter_column("candidate_id", nullable=False)
        batch.drop_index("ix_intake_slots_resume_slot")
        batch.drop_index("ix_intake_slots_resume_id")
        batch.drop_column("resume_id")
        batch.create_index(
            "ix_intake_slots_candidate_slot", ["candidate_id", "slot_key"], unique=True
        )


def downgrade() -> None:
    with op.batch_alter_table("intake_slots") as batch:
        batch.add_column(sa.Column("resume_id", sa.Integer, nullable=True))

    conn = op.get_bind()
    candidates = conn.execute(sa.text(
        "SELECT id, boss_id, name, job_id, intake_status, "
        "intake_started_at, intake_completed_at, created_at, updated_at "
        "FROM intake_candidates"
    )).fetchall()
    id_map = {}
    for c in candidates:
        res = conn.execute(sa.text(
            "INSERT INTO resumes (boss_id, name, job_id, status, source, intake_status, "
            "intake_started_at, intake_completed_at, created_at, updated_at) "
            "VALUES (:boss_id, :name, :job_id, 'passed', 'boss_zhipin', :st, "
            ":s_at, :c_at, :cr, :up)"
        ), dict(boss_id=c[1], name=c[2], job_id=c[3], st=c[4],
                s_at=c[5], c_at=c[6], cr=c[7], up=c[8]))
        id_map[c[0]] = res.lastrowid or conn.execute(
            sa.text("SELECT last_insert_rowid()")
        ).scalar()
    for old, new in id_map.items():
        conn.execute(sa.text(
            "UPDATE intake_slots SET resume_id = :new WHERE candidate_id = :old"
        ), dict(new=new, old=old))

    with op.batch_alter_table("intake_slots") as batch:
        batch.drop_index("ix_intake_slots_candidate_slot")
        batch.alter_column("resume_id", nullable=False)
        batch.drop_index("ix_intake_slots_candidate_id")
        batch.drop_constraint("fk_intake_slots_candidate_id", type_="foreignkey")
        batch.drop_column("candidate_id")
        batch.create_index("ix_intake_slots_resume_slot", ["resume_id", "slot_key"], unique=True)
        batch.create_index("ix_intake_slots_resume_id", ["resume_id"])

    op.drop_index("ix_intake_candidates_job_id", table_name="intake_candidates")
    op.drop_index("ix_intake_candidates_status", table_name="intake_candidates")
    op.drop_index("ix_intake_candidates_boss_id", table_name="intake_candidates")
    op.drop_table("intake_candidates")
