"""seed skills library

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-20 11:27:15.634431

"""
import json
from pathlib import Path
from alembic import op
import sqlalchemy as sa


revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    seed_path = Path(__file__).resolve().parents[2] / "app" / "core" / "competency" / "seed_skills.json"
    with seed_path.open(encoding="utf-8") as f:
        seeds = json.load(f)

    conn = op.get_bind()
    for s in seeds:
        conn.execute(
            sa.text("""
                INSERT OR IGNORE INTO skills
                  (canonical_name, aliases, category, source, pending_classification, usage_count)
                VALUES
                  (:name, :aliases, :category, 'seed', 0, 0)
            """),
            {
                "name": s["name"],
                "aliases": json.dumps(s.get("aliases", []), ensure_ascii=False),
                "category": s["category"],
            },
        )


def downgrade() -> None:
    op.execute("DELETE FROM skills WHERE source='seed'")
