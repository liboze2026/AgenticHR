"""Shared fixtures for recruit_bot module tests.

Centralizes the M2 baseline seed + 0010 migration + SQLAlchemy session setup
so each test module (T2/T3/T4/T5) doesn't re-declare the same plumbing.
"""
import sqlite3

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import sessionmaker


def _seed_m2_schema(db_path: str) -> None:
    """模拟 M2 baseline: users/jobs/resumes + audit_events 已存在, 为迁移提供 ALTER 目标.

    包含 resumes 表完整字段 (bachelor_school / work_years / skills 等),
    以及 F2 在 jobs 上新增的 competency_model / competency_model_status /
    scoring_weights / jd_text 列, 便于 T3 evaluate_and_record 测试直接
    创建带能力模型的 Job. audit_events 也一并建出 (0004 迁移产物),
    因为 F3 决策路径会 log_event.
    """
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username VARCHAR(50) UNIQUE NOT NULL,
            password_hash VARCHAR(200) NOT NULL,
            display_name VARCHAR(100) DEFAULT '',
            is_active BOOLEAN DEFAULT 1,
            created_at DATETIME
        );
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
            updated_at DATETIME,
            jd_text TEXT DEFAULT '' NOT NULL,
            competency_model JSON,
            competency_model_status VARCHAR(20) DEFAULT 'none' NOT NULL,
            scoring_weights JSON
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
            seniority VARCHAR(20) NOT NULL DEFAULT '',
            created_at DATETIME,
            updated_at DATETIME
        );
        CREATE TABLE IF NOT EXISTS audit_events (
            event_id TEXT PRIMARY KEY,
            f_stage TEXT NOT NULL,
            action TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id INTEGER,
            input_hash TEXT,
            output_hash TEXT,
            prompt_version TEXT,
            model_name TEXT,
            model_version TEXT,
            reviewer_id INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
            retention_until DATETIME
        );
        CREATE TABLE IF NOT EXISTS matching_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            resume_id INTEGER NOT NULL,
            job_id INTEGER NOT NULL,
            total_score INTEGER NOT NULL DEFAULT 0,
            skill_score INTEGER NOT NULL DEFAULT 0,
            experience_score INTEGER NOT NULL DEFAULT 0,
            seniority_score INTEGER NOT NULL DEFAULT 0,
            education_score INTEGER NOT NULL DEFAULT 0,
            industry_score INTEGER NOT NULL DEFAULT 0,
            hard_gate_passed INTEGER NOT NULL DEFAULT 0,
            missing_must_haves TEXT DEFAULT '[]',
            evidence TEXT DEFAULT '{}',
            tags TEXT DEFAULT '[]',
            competency_hash TEXT DEFAULT '',
            weights_hash TEXT DEFAULT '',
            scored_at DATETIME,
            job_action VARCHAR(20) DEFAULT ''
        );
        CREATE UNIQUE INDEX IF NOT EXISTS ix_matching_results_resume_job
            ON matching_results(resume_id, job_id);
    """)
    conn.commit()
    conn.close()


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Yield a SQLAlchemy session bound to a freshly-migrated 0010 SQLite DB.

    - Seeds M2 baseline via ``_seed_m2_schema`` (includes audit_events /
      matching_results / F2 jobs columns)
    - Stamps alembic at 0009, upgrades to 0010 (F3 migration under test)
    - Monkeypatches ``app.database.engine`` so any module that imports it
      at call-time sees the temp engine
    - Monkeypatches ``app.core.audit.logger._session_factory`` so F3 audit
      writes hit the temp DB instead of the production engine bound at
      import time
    """
    dbp = tmp_path / "t.db"
    _seed_m2_schema(str(dbp))
    url = f"sqlite:///{dbp}"
    cfg = Config("migrations/alembic.ini")
    cfg.set_main_option("script_location", "migrations")
    cfg.set_main_option("sqlalchemy.url", url)
    command.stamp(cfg, "0009")
    command.upgrade(cfg, "0010")
    engine = sa.create_engine(url, connect_args={"check_same_thread": False})
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr("app.database.engine", engine)
    # audit logger binds _session_factory at import time to production engine;
    # rebind to the temp engine so log_event writes visible rows for tests.
    import app.core.audit.logger as audit_logger
    monkeypatch.setattr(audit_logger, "_session_factory", factory)
    # F2 skill scorer runs bge-m3 vector similarity against a skills table
    # that doesn't exist in this migration path (0001-0009 are stamped, not run).
    # Short-circuit to a deterministic fake so score_pair produces stable
    # numbers regardless of embedding infra (matches the same monkeypatch
    # used by tests/integration/test_f2_e2e_smoke.py).
    monkeypatch.setattr(
        "app.modules.matching.scorers.skill._max_vector_similarity",
        lambda name, resume_names, db_session=None: (
            0.95 if name in (resume_names or []) else 0.0
        ),
    )
    # Also short-circuit LLM evidence enhancement — deterministic fallback.
    from unittest.mock import AsyncMock
    monkeypatch.setattr(
        "app.modules.matching.service.enhance_evidence_with_llm",
        AsyncMock(side_effect=lambda ev, *a, **kw: ev),
    )
    session = factory()
    yield session
    session.close()
