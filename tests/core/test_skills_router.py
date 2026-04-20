"""/api/skills 路由."""
import pytest
from fastapi.testclient import TestClient
from alembic import command
from alembic.config import Config
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    url = f"sqlite:///{db}"

    # upgrade 0005 前先 seed jobs 表（0005 做 ALTER TABLE jobs ADD COLUMN）
    # 注意：不能预先创建 0005 要 ALTER 的列（competency_model 等），否则会报 duplicate column
    engine_tmp = sa.create_engine(url, connect_args={"check_same_thread": False})
    with engine_tmp.connect() as conn:
        conn.execute(sa.text("""CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT, description TEXT, requirements TEXT,
            status TEXT DEFAULT 'open'
        )"""))
        conn.commit()
    engine_tmp.dispose()

    cfg = Config("migrations/alembic.ini")
    cfg.set_main_option("script_location", "migrations")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "0006")
    engine = sa.create_engine(url, connect_args={"check_same_thread": False})
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr("app.database.engine", engine)
    monkeypatch.setattr(
        "app.core.competency.skill_library._session_factory", factory
    )
    monkeypatch.setattr("app.core.audit.logger._session_factory", factory)
    monkeypatch.setenv("AGENTICHR_TEST_BYPASS_AUTH", "1")
    return TestClient(app)


def test_list_all(client):
    r = client.get("/api/skills")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] >= 50
    assert any(s["canonical_name"] == "Python" for s in data["items"])


def test_search(client):
    r = client.get("/api/skills", params={"search": "Python"})
    data = r.json()
    assert data["total"] >= 1
    assert any(s["canonical_name"] == "Python" for s in data["items"])


def test_list_pending_only(client):
    r = client.get("/api/skills", params={"pending": "true"})
    # seed 没有 pending, 应为空或只有测试过程中插入的
    assert r.status_code == 200


def test_categories(client):
    r = client.get("/api/skills/categories")
    data = r.json()
    assert "language" in data["categories"]
    assert "framework" in data["categories"]


def test_create_new_skill(client):
    r = client.post("/api/skills", json={
        "canonical_name": "HandMade",
        "category": "tool",
        "aliases": ["hm"],
    })
    assert r.status_code == 200
    data = r.json()
    assert data["canonical_name"] == "HandMade"
    assert data["source"] == "seed_manual"
