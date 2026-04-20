"""core.competency.extractor — JD → CompetencyModel."""
import json
import pytest
from unittest.mock import AsyncMock, patch
from alembic import command
from alembic.config import Config
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker


def _seed_jobs_table(db_path):
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


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """每个 extractor 测试用独立 DB, 避免污染真实 skills 表."""
    from app.core.competency.skill_library import SkillCache
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
    yield


_VALID_JSON = json.dumps({
    "hard_skills": [
        {"name": "Python", "level": "精通", "weight": 9, "must_have": True},
        {"name": "FastAPI", "level": "熟练", "weight": 7, "must_have": False},
    ],
    "soft_skills": [{"name": "沟通能力", "weight": 6, "assessment_stage": "面试"}],
    "experience": {"years_min": 3, "years_max": 7, "industries": [], "company_scale": None},
    "education": {"min_level": "本科", "preferred_level": None, "prestigious_bonus": False},
    "job_level": "P6",
    "bonus_items": ["开源贡献"],
    "exclusions": [],
    "assessment_dimensions": [
        {"name": "系统设计", "description": "", "question_types": ["白板"]},
    ],
})


@pytest.mark.asyncio
async def test_extract_success():
    from app.core.competency.extractor import extract_competency
    mock_llm = AsyncMock()
    mock_llm.complete = AsyncMock(return_value=_VALID_JSON)
    mock_llm.embed_batch = AsyncMock(return_value=[[1.0, 0, 0], [0.9, 0.1, 0]])
    mock_llm.model = "glm-4-flash"
    with patch("app.core.competency.extractor.get_llm_provider", return_value=mock_llm), \
         patch("app.core.competency.normalizer.get_llm_provider", return_value=mock_llm):
        model = await extract_competency(
            jd_text="招聘高级后端工程师...",
            job_id=1,
        )
    assert len(model.hard_skills) == 2
    assert model.hard_skills[0].name == "Python"
    assert model.education.min_level == "本科"
    assert model.source_jd_hash


@pytest.mark.asyncio
async def test_extract_invalid_json_retries():
    from app.core.competency.extractor import extract_competency
    mock_llm = AsyncMock()
    mock_llm.complete = AsyncMock(side_effect=[
        "not json at all",
        "also not json",
        _VALID_JSON,
    ])
    mock_llm.embed_batch = AsyncMock(return_value=[[1.0, 0, 0], [0.9, 0.1, 0]])
    mock_llm.model = "glm-4-flash"
    with patch("app.core.competency.extractor.get_llm_provider", return_value=mock_llm), \
         patch("app.core.competency.normalizer.get_llm_provider", return_value=mock_llm):
        model = await extract_competency(jd_text="jd", job_id=1)
    assert mock_llm.complete.await_count == 3
    assert len(model.hard_skills) == 2


@pytest.mark.asyncio
async def test_extract_all_retries_fail_raises():
    from app.core.competency.extractor import extract_competency, ExtractionFailedError
    mock_llm = AsyncMock()
    mock_llm.complete = AsyncMock(return_value="never valid")
    mock_llm.model = "glm-4-flash"
    with patch("app.core.competency.extractor.get_llm_provider", return_value=mock_llm):
        with pytest.raises(ExtractionFailedError):
            await extract_competency(jd_text="jd", job_id=1)


@pytest.mark.asyncio
async def test_extract_llm_http_error_raises():
    from app.core.competency.extractor import extract_competency, ExtractionFailedError
    from app.core.llm.provider import LLMError
    mock_llm = AsyncMock()
    mock_llm.complete = AsyncMock(side_effect=LLMError("net down"))
    mock_llm.model = "glm-4-flash"
    with patch("app.core.competency.extractor.get_llm_provider", return_value=mock_llm):
        with pytest.raises(ExtractionFailedError):
            await extract_competency(jd_text="jd", job_id=1)


@pytest.mark.asyncio
async def test_extract_audits_extract_action():
    from app.core.competency.extractor import extract_competency
    seen = []

    def fake_log(**kwargs):
        seen.append(kwargs)
        return "eid"

    mock_llm = AsyncMock()
    mock_llm.complete = AsyncMock(return_value=_VALID_JSON)
    mock_llm.embed_batch = AsyncMock(return_value=[[1.0, 0, 0], [0.9, 0.1, 0]])
    mock_llm.model = "glm-4-flash"
    with patch("app.core.competency.extractor.get_llm_provider", return_value=mock_llm), \
         patch("app.core.competency.normalizer.get_llm_provider", return_value=mock_llm), \
         patch("app.core.competency.extractor.log_event", fake_log), \
         patch("app.core.competency.normalizer.log_event", fake_log):
        await extract_competency(jd_text="jd", job_id=1)
    actions = [s["action"] for s in seen]
    assert "extract" in actions
