"""core.competency.skill_library — CRUD + cache."""
import pytest
from alembic import command
from alembic.config import Config
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker


def _seed_jobs_table(db_path):
    """0005 需要 jobs 表存在. 空 tmp DB 需要先手工建出."""
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
def lib(tmp_path, monkeypatch):
    from app.core.competency.skill_library import SkillLibrary, SkillCache
    db = tmp_path / "t.db"
    _seed_jobs_table(db)
    url = f"sqlite:///{db}"
    cfg = Config("migrations/alembic.ini")
    cfg.set_main_option("script_location", "migrations")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "0006")

    engine = sa.create_engine(url, connect_args={"check_same_thread": False})
    monkeypatch.setattr("app.database.engine", engine)
    from sqlalchemy.orm import sessionmaker as sm
    session_factory = sm(bind=engine)
    from app.core.competency import skill_library as lib_mod
    monkeypatch.setattr(lib_mod, "_session_factory", session_factory)
    SkillCache.invalidate()
    return SkillLibrary()


def test_list_seed_skills(lib):
    all_skills = lib.list_all()
    assert len(all_skills) >= 50
    python = next(s for s in all_skills if s["canonical_name"] == "Python")
    assert python["category"] == "language"
    assert "python3" in python["aliases"]


def test_find_by_name(lib):
    s = lib.find_by_name("Python")
    assert s is not None
    assert s["canonical_name"] == "Python"
    assert lib.find_by_name("不存在的技能") is None


def test_insert_new_skill(lib):
    new_id = lib.insert(
        canonical_name="Py后端",
        embedding=b"\x00\x00\x80\x3f",
        source="llm_extracted",
        pending_classification=True,
    )
    assert new_id > 0
    found = lib.find_by_name("Py后端")
    assert found["pending_classification"] is True
    assert found["source"] == "llm_extracted"


def test_insert_duplicate_name_raises(lib):
    with pytest.raises(Exception):
        lib.insert(canonical_name="Python", source="manual")


def test_add_alias(lib):
    lib.add_alias_if_absent("Python", "Py3k")
    s = lib.find_by_name("Python")
    assert "Py3k" in s["aliases"]
    lib.add_alias_if_absent("Python", "Py3k")
    s2 = lib.find_by_name("Python")
    assert s2["aliases"].count("Py3k") == 1


def test_increment_usage(lib):
    before_id = lib.find_by_name("Python")["id"]
    before = lib.find_by_name("Python")["usage_count"]
    lib.increment_usage(before_id)
    after = lib.find_by_name("Python")["usage_count"]
    assert after == before + 1


def test_search_by_name_substring(lib):
    hits = lib.search("Python")
    assert any(h["canonical_name"] == "Python" for h in hits)


def test_cache_reload_after_insert(lib):
    from app.core.competency.skill_library import SkillCache
    SkillCache.all()
    lib.insert(canonical_name="NewSkillXYZ", source="manual")
    SkillCache.invalidate()
    all2 = SkillCache.all()
    assert any(s["canonical_name"] == "NewSkillXYZ" for s in all2)


def test_list_pending_classification(lib):
    lib.insert(canonical_name="PendingA", source="llm_extracted", pending_classification=True)
    lib.insert(canonical_name="PendingB", source="llm_extracted", pending_classification=True)
    pending = lib.list_pending()
    names = {p["canonical_name"] for p in pending}
    assert names >= {"PendingA", "PendingB"}
