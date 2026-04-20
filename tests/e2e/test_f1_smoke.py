"""F1 E2E smoke: JD → extract → HITL approve → screen.

流程覆盖:
  1. 创建岗位 (带 jd_text) + 3 条简历
  2. Mock LLM 抽取 competency_model → status=draft + HITL task 创建
  3. HITL approve → 触发 app.main 中已注册的 _on_competency_approved callback
  4. 验证 jobs.competency_model_status=approved + 扁平字段双写
  5. 跑硬筛 → 合格 1 / 不合格 2，符合能力模型预期
"""
import json
import sqlite3
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from alembic import command
from alembic.config import Config
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from app.main import app


_VALID_LLM_OUTPUT = json.dumps({
    "hard_skills": [
        {"name": "Python", "level": "精通", "weight": 9, "must_have": True},
        {"name": "FastAPI", "level": "熟练", "weight": 7, "must_have": True},
    ],
    "soft_skills": [],
    "experience": {"years_min": 3, "years_max": 7, "industries": [], "company_scale": None},
    "education": {"min_level": "本科", "preferred_level": None, "prestigious_bonus": False},
    "job_level": "P6", "bonus_items": [], "exclusions": [], "assessment_dimensions": [],
})


def _seed_m2_base_schema(db_path: str) -> None:
    """迁移 0001 是 no-op 基线 (假设 M2 表已存在), 迁移 0005 需要 jobs 表.
    全量建出 M2 时期的基础表, 供后续 alembic upgrade 增量演化."""
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER DEFAULT 0,
            title VARCHAR(200) NOT NULL,
            department VARCHAR(100) DEFAULT '',
            education_min VARCHAR(50) DEFAULT '',
            work_years_min INTEGER DEFAULT 0,
            work_years_max INTEGER DEFAULT 99,
            salary_min REAL DEFAULT 0,
            salary_max REAL DEFAULT 0,
            required_skills TEXT DEFAULT '',
            soft_requirements TEXT DEFAULT '',
            greeting_templates TEXT DEFAULT '',
            is_active BOOLEAN DEFAULT 1,
            created_at DATETIME,
            updated_at DATETIME
        );
        CREATE TABLE IF NOT EXISTS resumes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER DEFAULT 0,
            name VARCHAR(100) NOT NULL,
            phone VARCHAR(20) DEFAULT '',
            email VARCHAR(200) DEFAULT '',
            education VARCHAR(50) DEFAULT '',
            bachelor_school VARCHAR(200) DEFAULT '',
            master_school VARCHAR(200) DEFAULT '',
            phd_school VARCHAR(200) DEFAULT '',
            qr_code_path VARCHAR(500) DEFAULT '',
            work_years INTEGER DEFAULT 0,
            expected_salary_min REAL DEFAULT 0,
            expected_salary_max REAL DEFAULT 0,
            job_intention VARCHAR(200) DEFAULT '',
            skills TEXT DEFAULT '',
            work_experience TEXT DEFAULT '',
            project_experience TEXT DEFAULT '',
            self_evaluation TEXT DEFAULT '',
            source VARCHAR(50) DEFAULT '',
            raw_text TEXT DEFAULT '',
            pdf_path VARCHAR(500) DEFAULT '',
            status VARCHAR(20) DEFAULT 'passed',
            ai_parsed VARCHAR(10) DEFAULT 'no',
            ai_score REAL,
            ai_summary TEXT DEFAULT '',
            reject_reason VARCHAR(200) DEFAULT '',
            created_at DATETIME,
            updated_at DATETIME
        );
        CREATE TABLE IF NOT EXISTS interviewers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR(100) NOT NULL,
            phone VARCHAR(20) DEFAULT '',
            feishu_user_id VARCHAR(100) DEFAULT '',
            email VARCHAR(200) DEFAULT '',
            department VARCHAR(100) DEFAULT '',
            created_at DATETIME
        );
        CREATE TABLE IF NOT EXISTS interviewer_availability (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            interviewer_id INTEGER NOT NULL,
            start_time DATETIME NOT NULL,
            end_time DATETIME NOT NULL,
            source VARCHAR(50) DEFAULT 'manual'
        );
        CREATE TABLE IF NOT EXISTS interviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER DEFAULT 0,
            resume_id INTEGER,
            job_id INTEGER,
            interviewer_id INTEGER,
            scheduled_time DATETIME,
            duration_minutes INTEGER DEFAULT 60,
            location VARCHAR(200) DEFAULT '',
            status VARCHAR(20) DEFAULT 'scheduled',
            notes TEXT DEFAULT '',
            feishu_event_id VARCHAR(200) DEFAULT '',
            meeting_account VARCHAR(50) DEFAULT '',
            meeting_id VARCHAR(50) DEFAULT '',
            meeting_topic VARCHAR(200) DEFAULT '',
            created_at DATETIME,
            updated_at DATETIME
        );
        CREATE TABLE IF NOT EXISTS notification_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER DEFAULT 0,
            resume_id INTEGER,
            channel VARCHAR(50) DEFAULT '',
            status VARCHAR(20) DEFAULT '',
            message TEXT DEFAULT '',
            created_at DATETIME
        );
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username VARCHAR(100) NOT NULL,
            email VARCHAR(200) DEFAULT '',
            hashed_password VARCHAR(200) NOT NULL,
            is_active BOOLEAN DEFAULT 1,
            created_at DATETIME,
            updated_at DATETIME
        );
    """)
    conn.commit()
    conn.close()


@pytest.fixture
def env(tmp_path, monkeypatch):
    """独立测试 DB + 全量 session factory monkeypatching."""
    from app.core.competency.skill_library import SkillCache

    db = tmp_path / "e2e.db"
    # M2 基础 schema 必须在 alembic upgrade 前建好 (0001 是 no-op 基线)
    _seed_m2_base_schema(str(db))

    url = f"sqlite:///{db}"
    cfg = Config("migrations/alembic.ini")
    cfg.set_main_option("script_location", "migrations")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "0006")

    engine = sa.create_engine(url, connect_args={"check_same_thread": False})
    factory = sessionmaker(bind=engine)

    # Patch module-level engine + all _session_factory references
    import app.database as db_mod
    import app.core.audit.logger as audit_mod
    import app.core.hitl.service as hitl_mod
    import app.core.competency.skill_library as sl_mod
    import app.modules.screening.competency_service as cs_mod

    monkeypatch.setattr(db_mod, "engine", engine)
    monkeypatch.setattr(db_mod, "SessionLocal", factory)
    monkeypatch.setattr(audit_mod, "_session_factory", factory)
    monkeypatch.setattr(hitl_mod, "_session_factory", factory)
    monkeypatch.setattr(sl_mod, "_session_factory", factory)
    monkeypatch.setattr(cs_mod, "_session_factory", factory)

    # Override FastAPI dependencies
    from app.database import get_db
    from app.modules.auth.deps import get_current_user_id

    def override_get_db():
        s = factory()
        try:
            yield s
        finally:
            s.close()

    def override_user_id() -> int:
        return 0

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user_id] = override_user_id

    # Invalidate SkillCache so it re-loads from the test DB
    SkillCache.invalidate()

    # Auth bypass
    monkeypatch.setenv("AGENTICHR_TEST_BYPASS_AUTH", "1")

    yield factory

    app.dependency_overrides.clear()
    SkillCache.invalidate()


def test_f1_e2e_smoke(env, monkeypatch):
    """JD → 抽取 → HITL approve → 筛选通过/不通过符合 competency_model."""
    client = TestClient(app)

    # ── Step 1: 创建岗位 + 3 条简历 ──────────────────────────────────────
    from app.modules.screening.models import Job
    from app.modules.resume.models import Resume

    s = env()
    job = Job(title="Python 后端", jd_text="招聘资深 Python 后端工程师")
    resume_pass = Resume(name="合格 A", education="本科", work_years=5, skills="Python, FastAPI")
    resume_no_skill = Resume(name="不合格 (缺 FastAPI)", education="本科", work_years=5, skills="Python")
    resume_no_edu = Resume(name="不合格 (学历)", education="大专", work_years=5, skills="Python,FastAPI")
    s.add_all([job, resume_pass, resume_no_skill, resume_no_edu])
    s.commit()
    jid = job.id
    s.close()

    # ── Step 2: mock LLM 抽取 ─────────────────────────────────────────────
    mock_llm = AsyncMock()
    mock_llm.complete = AsyncMock(return_value=_VALID_LLM_OUTPUT)
    mock_llm.embed_batch = AsyncMock(return_value=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    mock_llm.model = "mock-model"

    with patch("app.core.competency.extractor.get_llm_provider", return_value=mock_llm), \
         patch("app.core.competency.normalizer.get_llm_provider", return_value=mock_llm):
        resp = client.post(f"/api/screening/jobs/{jid}/competency/extract")

    assert resp.status_code == 200, f"extract failed: {resp.text}"
    data = resp.json()
    assert data["status"] == "draft", f"expected draft, got: {data}"
    task_id = data["hitl_task_id"]
    assert isinstance(task_id, int)

    # ── Step 3: HITL approve ───────────────────────────────────────────────
    # _on_competency_approved 已在 app.main 导入时注册，无需重复注册
    resp = client.post(f"/api/hitl/tasks/{task_id}/approve", json={"note": "ok"})
    assert resp.status_code == 200, f"approve failed: {resp.text}"
    assert resp.json()["status"] == "approved"

    # ── Step 4: 验证 competency_model 写入 + 扁平字段双写 ─────────────────
    s = env()
    job = s.query(Job).filter(Job.id == jid).first()
    assert job.competency_model_status == "approved", f"status={job.competency_model_status}"
    assert job.required_skills is not None
    assert "Python" in job.required_skills, f"required_skills={job.required_skills}"
    assert "FastAPI" in job.required_skills, f"required_skills={job.required_skills}"
    s.close()

    # ── Step 5: 跑硬筛，验证通过/不通过符合预期 ───────────────────────────
    # resume_ids 是 query param（可选），不传则筛全部非 rejected 简历
    resp = client.post(f"/api/screening/jobs/{jid}/screen")
    assert resp.status_code == 200, f"screen failed: {resp.text}"
    data = resp.json()

    assert data["passed"] == 1, f"expected 1 passed, got {data['passed']}: {data}"
    assert data["rejected"] == 2, f"expected 2 rejected, got {data['rejected']}: {data}"

    names_passed = {r["resume_name"] for r in data["results"] if r["passed"]}
    assert names_passed == {"合格 A"}, f"unexpected passed: {names_passed}"
