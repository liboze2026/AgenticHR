"""POST /api/recruit/record-greet."""
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
    from app.core.audit import logger as audit_mod
    monkeypatch.setattr(audit_mod, "_session_factory", factory)

    session = factory()
    from app.modules.auth.models import User
    from app.modules.resume.models import Resume
    u = User(username="hr1", password_hash="x"); session.add(u); session.commit()
    uid = u.id
    r = Resume(user_id=uid, name="张三", boss_id="b1", source="boss_zhipin",
               greet_status="pending_greet")
    session.add(r); session.commit()
    rid = r.id
    session.close()

    from app.main import app
    from app.modules.auth.deps import get_current_user_id
    app.dependency_overrides[get_current_user_id] = lambda: uid
    try:
        with TestClient(app) as c:
            yield c, rid
    finally:
        app.dependency_overrides.pop(get_current_user_id, None)


def test_record_greet_success_updates_status(client):
    c, rid = client
    r = c.post("/api/recruit/record-greet",
               json={"resume_id": rid, "success": True})
    assert r.status_code == 200
    assert r.json()["status"] == "recorded"


def test_record_greet_failed_writes_error(client):
    c, rid = client
    r = c.post("/api/recruit/record-greet",
               json={"resume_id": rid, "success": False, "error_msg": "risk_control_detected"})
    assert r.status_code == 200


def test_record_greet_foreign_resume_404(client):
    c, rid = client
    r = c.post("/api/recruit/record-greet",
               json={"resume_id": 99999, "success": True})
    assert r.status_code == 404
