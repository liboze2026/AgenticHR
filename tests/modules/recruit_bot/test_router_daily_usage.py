"""GET /api/recruit/daily-usage + PUT /api/recruit/daily-cap."""
import pytest
from alembic import command
from alembic.config import Config
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    dbp = tmp_path / "t.db"
    url = f"sqlite:///{dbp}"
    from tests.modules.recruit_bot.conftest import _seed_m2_schema
    _seed_m2_schema(str(dbp))
    cfg = Config("migrations/alembic.ini")
    cfg.set_main_option("script_location", "migrations")
    cfg.set_main_option("sqlalchemy.url", url)
    command.stamp(cfg, "0009")
    command.upgrade(cfg, "0011")
    engine = sa.create_engine(url, connect_args={"check_same_thread": False})
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr("app.database.engine", engine)
    monkeypatch.setattr("app.database.SessionLocal", factory)
    session = factory()
    from app.modules.auth.models import User
    u = User(username="hr1", password_hash="x", daily_cap=500); session.add(u); session.commit()
    uid = u.id
    session.close()
    from app.main import app
    from app.modules.auth.deps import get_current_user_id
    app.dependency_overrides[get_current_user_id] = lambda: uid
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_current_user_id, None)


def test_daily_usage_initial(client):
    r = client.get("/api/recruit/daily-usage")
    assert r.status_code == 200
    d = r.json()
    assert d["used"] == 0
    assert d["cap"] == 500
    assert d["remaining"] == 500


def test_daily_cap_update(client):
    r = client.put("/api/recruit/daily-cap", json={"cap": 2000})
    assert r.status_code == 200
    assert r.json()["cap"] == 2000
    r2 = client.get("/api/recruit/daily-usage")
    assert r2.json()["cap"] == 2000


def test_daily_cap_rejects_negative(client):
    r = client.put("/api/recruit/daily-cap", json={"cap": -1})
    assert r.status_code == 422


def test_daily_cap_rejects_too_large(client):
    r = client.put("/api/recruit/daily-cap", json={"cap": 10001})
    assert r.status_code == 422
