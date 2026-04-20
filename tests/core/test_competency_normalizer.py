"""core.competency.normalizer — 技能归一化."""
import pytest
from unittest.mock import AsyncMock, patch
from alembic import command
from alembic.config import Config
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker


def _seed_jobs_table(db_path):
    """0005 需要 jobs 表存在."""
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title VARCHAR(200) NOT NULL
        )
    """)
    conn.commit()
    conn.close()


@pytest.fixture
def ready_db(tmp_path, monkeypatch):
    from app.core.competency.skill_library import SkillLibrary, SkillCache
    from app.core.vector.service import pack_vector

    db = tmp_path / "t.db"
    _seed_jobs_table(db)
    url = f"sqlite:///{db}"
    cfg = Config("migrations/alembic.ini")
    cfg.set_main_option("script_location", "migrations")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "0006")

    engine = sa.create_engine(url, connect_args={"check_same_thread": False})
    factory = sessionmaker(bind=engine)

    monkeypatch.setattr("app.database.engine", engine)
    from app.core.competency import skill_library as sl_mod
    from app.core.audit import logger as al_mod
    from app.core.hitl import service as hs_mod
    monkeypatch.setattr(sl_mod, "_session_factory", factory)
    monkeypatch.setattr(al_mod, "_session_factory", factory)
    monkeypatch.setattr(hs_mod, "_session_factory", factory)
    SkillCache.invalidate()

    lib = SkillLibrary()
    python_id = lib.find_by_name("Python")["id"]
    lib.update_embedding(python_id, pack_vector([1.0, 0.0, 0.0]))

    yield lib


@pytest.mark.asyncio
async def test_normalize_exact_match_reuses_skill(ready_db):
    from app.core.competency.normalizer import normalize_skills
    lib = ready_db
    mock_embed = AsyncMock(return_value=[[1.0, 0.0, 0.0]])
    with patch("app.core.competency.normalizer.get_llm_provider") as mock_get:
        mock_get.return_value.embed_batch = mock_embed
        results = await normalize_skills(["python3"], job_id=1)

    assert len(results) == 1
    python_id = lib.find_by_name("Python")["id"]
    assert results[0]["canonical_id"] == python_id

    p = lib.find_by_name("Python")
    assert "python3" in p["aliases"]


@pytest.mark.asyncio
async def test_normalize_low_similarity_creates_new_skill(ready_db):
    from app.core.competency.normalizer import normalize_skills
    from app.core.hitl.service import HitlService
    lib = ready_db
    mock_embed = AsyncMock(return_value=[[0.0, 1.0, 0.0]])
    with patch("app.core.competency.normalizer.get_llm_provider") as mock_get:
        mock_get.return_value.embed_batch = mock_embed
        results = await normalize_skills(["全新技能"], job_id=42)

    assert len(results) == 1
    new = lib.find_by_name("全新技能")
    assert new is not None
    assert new["pending_classification"] is True
    assert new["source"] == "llm_extracted"
    assert results[0]["canonical_id"] == new["id"]

    tasks = HitlService().list(stage="F1_skill_classification", status="pending")
    assert any(t["entity_id"] == new["id"] for t in tasks)


@pytest.mark.asyncio
async def test_normalize_threshold_boundary(ready_db):
    from app.core.competency.normalizer import normalize_skills
    lib = ready_db
    low = [0.849, (1.0 - 0.849**2)**0.5, 0.0]
    high = [0.851, (1.0 - 0.851**2)**0.5, 0.0]

    mock_embed = AsyncMock(side_effect=[[low], [high]])
    with patch("app.core.competency.normalizer.get_llm_provider") as mock_get:
        mock_get.return_value.embed_batch = mock_embed

        r1 = await normalize_skills(["低相似"], job_id=1)
        assert lib.find_by_name("低相似") is not None

        r2 = await normalize_skills(["高相似"], job_id=1)
        python_id = lib.find_by_name("Python")["id"]
        assert r2[0]["canonical_id"] == python_id


@pytest.mark.asyncio
async def test_normalize_empty_list(ready_db):
    from app.core.competency.normalizer import normalize_skills
    results = await normalize_skills([], job_id=1)
    assert results == []


@pytest.mark.asyncio
async def test_normalize_batch_multiple(ready_db):
    from app.core.competency.normalizer import normalize_skills
    lib = ready_db
    mock_embed = AsyncMock(return_value=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    with patch("app.core.competency.normalizer.get_llm_provider") as mock_get:
        mock_get.return_value.embed_batch = mock_embed
        results = await normalize_skills(["Python", "新技能A"], job_id=1)

    assert mock_embed.await_count == 1
    assert len(results) == 2
