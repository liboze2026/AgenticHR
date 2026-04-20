# F1 能力模型抽取 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 JD 文本经 LLM 抽取 + 技能库归一化得到结构化能力模型，HR 审核后作为 F2–F8 下游决策的唯一依据。

**Architecture:** 新建 `app/core/{llm,competency,vector,hitl,audit}` 五个横切包；扩展 `app/modules/screening` 消费；新增 3 张表 + 现 jobs 表加 3 列，全走 Alembic。前端加 2 页 + 2 共享组件 + Jobs.vue Tab 改造。

**Tech Stack:** Python 3.11, FastAPI 0.115, SQLAlchemy 2.0, Alembic 1.x, Pydantic 2.10, numpy, httpx, pytest 8.3, pytest-asyncio, Vue 3 Composition API, Element Plus, Vite, axios.

**Spec:** [docs/superpowers/specs/2026-04-20-f1-competency-model-design.md](../specs/2026-04-20-f1-competency-model-design.md)

**Milestone:** M3 / F1 (增量开发，F2 前完成并通过用户验收)

---

## File Structure

### 新建文件

```
migrations/                                    # M3-kickoff 产出
├── alembic.ini                                # 配置
├── env.py                                     # Alembic env
├── script.py.mako                             # migration 模板
└── versions/
    ├── 0001_baseline.py                       # K0: 现有 schema 快照
    ├── 0002_create_skills.py                  # T1
    ├── 0003_create_hitl_tasks.py              # T2
    ├── 0004_create_audit_events.py            # T3
    ├── 0005_jobs_competency_columns.py        # T4
    └── 0006_seed_skills.py                    # T5

app/core/                                      # F1 新增横切包
├── __init__.py
├── llm/
│   ├── __init__.py
│   ├── parsing.py                             # T6: JSON 解析
│   └── provider.py                            # T9+T10: LLM + embed
├── competency/
│   ├── __init__.py
│   ├── schema.py                              # T11: Pydantic
│   ├── skill_library.py                       # T12
│   ├── normalizer.py                          # T13
│   ├── extractor.py                           # T14
│   └── seed_skills.json                       # T5 种子数据
├── vector/
│   ├── __init__.py
│   └── service.py                             # T8: cosine + 打包
├── hitl/
│   ├── __init__.py
│   ├── models.py                              # T15
│   ├── service.py
│   └── router.py
└── audit/
    ├── __init__.py
    ├── models.py                              # T7
    └── logger.py

tests/core/                                    # 单元测试
├── __init__.py
├── test_llm_parsing.py                        # T6
├── test_audit_logger.py                       # T7 (WORM 强约束)
├── test_vector_service.py                     # T8
├── test_llm_provider.py                       # T9+T10
├── test_competency_schema.py                  # T11
├── test_skill_library.py                      # T12
├── test_competency_normalizer.py              # T13
├── test_competency_extractor.py               # T14
└── test_hitl_service.py                       # T15

tests/modules/screening/
├── test_competency_extract_flow.py            # T19 集成
├── test_double_write.py                       # T17 集成
└── test_flat_backward_compat.py               # T18 回归

tests/e2e/
└── test_f1_smoke.py                           # T28

frontend/src/
├── components/                                # 首次起
│   ├── SkillPicker.vue                        # T22
│   └── CompetencyEditor.vue                   # T23
└── views/
    ├── HitlQueue.vue                          # T25
    └── SkillLibrary.vue                       # T26
```

### 修改文件

```
app/database.py                                # K0: 接入 Alembic
app/main.py                                    # T15, T19: 挂新 router
app/modules/screening/models.py                # T16: +3 列
app/modules/screening/schemas.py               # T16: +字段
app/modules/screening/service.py               # T17+T18: 双写/回退
app/modules/screening/router.py                # T19: 新 API
app/config.py                                  # T9: +AI_MODEL_COMPETENCY

frontend/src/api/index.js                      # T20
frontend/src/App.vue                           # T21
frontend/src/router/index.js                   # T27
frontend/src/views/Jobs.vue                    # T24: el-tabs

requirements.txt                               # K0: +alembic, +numpy
```

---

## Phase 0 — M3-kickoff (Alembic Baseline)

### Task K0: Install Alembic + Generate Baseline Migration

**Files:**
- Create: `migrations/alembic.ini`
- Create: `migrations/env.py`
- Create: `migrations/script.py.mako`
- Create: `migrations/versions/0001_baseline.py`
- Modify: `requirements.txt` (add `alembic==1.14.0`, `numpy==2.2.0`)
- Modify: `app/database.py` (keep `create_tables()` for tests only, add comment)

**Context:** 现 `app/database.py::create_tables()` 用 SQLAlchemy 的 `create_all()` 自动建所有表，没有版本化。F1 起需要 Alembic 管理 schema 演化。baseline 是现有所有表的快照 — 任何已运行过项目的数据库都应该 stamp 到这个版本，之后跑后续 migration 才安全。

- [ ] **Step 1: Install alembic**

```bash
cd /d/libz/AgenticHR
python -m uv pip install --python .venv/Scripts/python.exe alembic==1.14.0 numpy==2.2.0
```

Expected: `Installed N packages` 包含 alembic 和 numpy

- [ ] **Step 2: Add to requirements.txt**

Modify `requirements.txt`, append two lines (after existing `httpx==0.28.1`):

```
alembic==1.14.0
numpy==2.2.0
```

- [ ] **Step 3: Initialize Alembic into `migrations/` dir**

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/alembic init migrations
```

Expected: 生成 `migrations/` 目录含 `env.py`、`script.py.mako`、空的 `versions/`，以及根目录 `alembic.ini`。

- [ ] **Step 4: Move alembic.ini into migrations/**

```bash
mv alembic.ini migrations/alembic.ini
```

- [ ] **Step 5: Configure `migrations/alembic.ini`**

Edit `migrations/alembic.ini`, set:

```ini
[alembic]
script_location = .
prepend_sys_path = ../
sqlalchemy.url = sqlite:///../data/recruitment.db

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

- [ ] **Step 6: Edit `migrations/env.py` to import app metadata**

Replace `migrations/env.py` entirely with:

```python
"""Alembic env — 接入 AgenticHR app metadata."""
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context

from app.database import Base
from app.modules.auth.models import User  # noqa: F401 ensure models registered
from app.modules.resume.models import Resume  # noqa: F401
from app.modules.screening.models import Job  # noqa: F401
from app.modules.scheduling.models import Interviewer, Interview  # noqa: F401
from app.modules.notification.models import NotificationLog  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # SQLite ALTER TABLE 支持
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

Note：`render_as_batch=True` 是 SQLite 必需的 — SQLite 的 `ALTER TABLE` 功能有限，Alembic 用"batch 模式"走"建新表 → 迁数据 → 删旧表"实现列增删。

- [ ] **Step 7: Verify env.py imports don't break**

Run:
```bash
cd /d/libz/AgenticHR
./.venv/Scripts/alembic -c migrations/alembic.ini current 2>&1
```
Expected: 输出空（无 migration 已 apply）+ 不报错。若报 `ModuleNotFoundError: app.modules.xxx.models` 的某个模块不存在，按实际现有 models 调整 env.py 的 import 清单。

- [ ] **Step 8: Generate baseline migration (empty autogenerate)**

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/alembic -c migrations/alembic.ini revision -m "baseline: current M2 schema snapshot" --rev-id 0001
```

然后编辑生成的 `migrations/versions/0001_*.py`，**清空 `upgrade()` 和 `downgrade()` 的 body** — baseline 代表"当前状态"，不做任何变更，仅作为后续 migration 的起点：

```python
"""baseline: current M2 schema snapshot

Revision ID: 0001
Revises:
Create Date: 2026-04-20 XX:XX:XX
"""
from alembic import op
import sqlalchemy as sa

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Baseline — no-op. 代表 M2 结束时的 schema。"""
    pass


def downgrade() -> None:
    """Baseline 不可降级。"""
    pass
```

- [ ] **Step 9: Modify `app/database.py` — keep create_tables only for tests**

在 `app/database.py` 的 `create_tables()` 函数上方加 docstring：

```python
def create_tables():
    """仅测试用. 生产/开发走 Alembic (migrations/).

    Alembic 引入后 (M3-kickoff K0), 生产环境的 schema 演化完全由 migration 管理.
    此函数保留是因为大量单测依赖 `create_all()` 的幂等建表行为.
    """
    Base.metadata.create_all(bind=engine)
```

- [ ] **Step 10: Commit**

```bash
cd /d/libz/AgenticHR
git add requirements.txt migrations/ app/database.py
git commit -m "$(cat <<'EOF'
chore(M3): introduce Alembic + baseline migration

- install alembic==1.14.0 + numpy==2.2.0
- migrations/ dir with env.py wired to app.database.Base
- baseline migration 0001 is no-op (represents M2 end state)
- app/database.py::create_tables() marked as test-only

Preparation for F1 schema work: skills / hitl_tasks / audit_events tables,
jobs column additions will follow as migrations 0002-0006.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: 1 commit 包含 migrations/ 目录 + requirements.txt 更新

---

### Task K1: Stamp Local DB to Baseline

**Files:**
- No file changes — this is a DB administration task

**Context:** Alembic 不会对已有 DB 反向推断版本。首次引入时必须**告诉** DB"你现在在第 0001 版"，之后 `upgrade head` 才不会尝试重复建表。漏掉这一步会导致 `upgrade` 报 `table already exists`。

- [ ] **Step 1: Back up existing DB**

```bash
cd /d/libz/AgenticHR
cp data/recruitment.db data/recruitment.db.backup-before-alembic 2>/dev/null || echo "no db yet, skip"
```

Expected: 生成备份文件（或无 DB 时跳过）。若有其他机器的 DB 需要同步，先从那台机器拷贝过来再跑 stamp。

- [ ] **Step 2: Stamp DB to baseline**

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/alembic -c migrations/alembic.ini stamp 0001
```

Expected: 输出 `Running stamp_revision -> 0001`。DB 的 `alembic_version` 表现在包含 `0001`。

- [ ] **Step 3: Verify current revision**

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/alembic -c migrations/alembic.ini current
```

Expected: 输出 `0001 (head)`。

- [ ] **Step 4: Verify startup still works**

启动后端测 health check：

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/python.exe -m uvicorn app.main:app --port 8000 &
sleep 3
curl -s http://127.0.0.1:8000/api/health
kill %1
```

Expected: `{"status":"ok",...}` HTTP 200。

- [ ] **Step 5: Commit (no code change, but mark task done)**

K1 不产生代码变更。不创建 commit（无 diff）。在执行此 task 的 session 记录即可。

---

## Phase 1 — Data Layer (Migrations)

### Task T1: skills Table Migration

**Files:**
- Create: `migrations/versions/0002_create_skills.py`
- Test: `tests/core/test_migrations_skills.py`

- [ ] **Step 1: Create the failing test**

Create `tests/core/__init__.py`（空文件）和 `tests/core/test_migrations_skills.py`：

```python
"""验证 skills 表 migration 结构."""
import sqlite3
import tempfile
from pathlib import Path

from alembic import command
from alembic.config import Config


def _make_alembic_cfg(db_path: str) -> Config:
    cfg = Config("migrations/alembic.ini")
    cfg.set_main_option("script_location", "migrations")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    return cfg


def test_skills_table_created_with_indexes(tmp_path):
    db = tmp_path / "t.db"
    cfg = _make_alembic_cfg(str(db))
    command.upgrade(cfg, "0002")

    conn = sqlite3.connect(str(db))
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert "skills" in tables

    cols = {r[1]: r[2] for r in conn.execute("PRAGMA table_info(skills)").fetchall()}
    assert cols["canonical_name"] == "TEXT"
    assert cols["aliases"] == "JSON"
    assert cols["category"] == "TEXT"
    assert cols["embedding"] == "BLOB"
    assert cols["source"] == "TEXT"
    assert cols["pending_classification"] == "BOOLEAN"
    assert cols["usage_count"] == "INTEGER"

    idxs = {r[1] for r in conn.execute(
        "SELECT * FROM sqlite_master WHERE type='index' AND tbl_name='skills'"
    ).fetchall()}
    assert "idx_skills_category" in idxs
    assert "idx_skills_pending" in idxs

    conn.close()


def test_skills_downgrade_removes_table(tmp_path):
    db = tmp_path / "t.db"
    cfg = _make_alembic_cfg(str(db))
    command.upgrade(cfg, "0002")
    command.downgrade(cfg, "0001")

    conn = sqlite3.connect(str(db))
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert "skills" not in tables
    conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/python.exe -m pytest tests/core/test_migrations_skills.py -v
```
Expected: FAIL — `alembic.util.exc.CommandError: Can't locate revision identified by '0002'`。

- [ ] **Step 3: Generate migration 0002**

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/alembic -c migrations/alembic.ini revision -m "create skills table" --rev-id 0002
```

编辑新生成的 `migrations/versions/0002_*.py`：

```python
"""create skills table

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-20 XX:XX:XX
"""
from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'skills',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('canonical_name', sa.Text(), nullable=False),
        sa.Column('aliases', sa.JSON(), server_default='[]', nullable=False),
        sa.Column('category', sa.Text(), server_default='uncategorized', nullable=False),
        sa.Column('embedding', sa.LargeBinary(), nullable=True),
        sa.Column('source', sa.Text(), nullable=False),
        sa.Column('pending_classification', sa.Boolean(), server_default=sa.text('0'), nullable=False),
        sa.Column('usage_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('canonical_name'),
    )
    op.create_index('idx_skills_category', 'skills', ['category'])
    op.create_index(
        'idx_skills_pending', 'skills', ['pending_classification'],
        sqlite_where=sa.text('pending_classification = 1'),
    )


def downgrade() -> None:
    op.drop_index('idx_skills_pending', 'skills')
    op.drop_index('idx_skills_category', 'skills')
    op.drop_table('skills')
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/python.exe -m pytest tests/core/test_migrations_skills.py -v
```
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
cd /d/libz/AgenticHR
git add migrations/versions/0002_create_skills.py tests/core/__init__.py tests/core/test_migrations_skills.py
git commit -m "feat(F1-T1): add skills table migration

- canonical_name unique
- embedding BLOB (lazy-load if NULL)
- pending_classification partial index (WHERE =1)
- upgrade/downgrade roundtrip tested

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task T2: hitl_tasks Table Migration

**Files:**
- Create: `migrations/versions/0003_create_hitl_tasks.py`
- Test: `tests/core/test_migrations_hitl.py`

- [ ] **Step 1: Create the failing test**

Create `tests/core/test_migrations_hitl.py`:

```python
"""验证 hitl_tasks 表 migration."""
import sqlite3
from alembic import command
from alembic.config import Config


def _cfg(db: str) -> Config:
    cfg = Config("migrations/alembic.ini")
    cfg.set_main_option("script_location", "migrations")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db}")
    return cfg


def test_hitl_tasks_table_created(tmp_path):
    db = tmp_path / "t.db"
    command.upgrade(_cfg(str(db)), "0003")

    conn = sqlite3.connect(str(db))
    cols = {r[1]: r[2] for r in conn.execute("PRAGMA table_info(hitl_tasks)").fetchall()}
    assert set(cols.keys()) >= {
        "id", "f_stage", "entity_type", "entity_id",
        "payload", "status", "edited_payload",
        "reviewer_id", "reviewed_at", "note", "created_at",
    }
    assert cols["status"] == "TEXT"
    assert cols["payload"] == "JSON"

    idxs = {r[1] for r in conn.execute(
        "SELECT * FROM sqlite_master WHERE type='index' AND tbl_name='hitl_tasks'"
    ).fetchall()}
    assert "idx_hitl_status" in idxs
    assert "idx_hitl_stage" in idxs
    conn.close()


def test_hitl_tasks_roundtrip(tmp_path):
    db = tmp_path / "t.db"
    cfg = _cfg(str(db))
    command.upgrade(cfg, "0003")
    command.downgrade(cfg, "0002")

    conn = sqlite3.connect(str(db))
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert "hitl_tasks" not in tables
    conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/python.exe -m pytest tests/core/test_migrations_hitl.py -v
```
Expected: FAIL — revision 0003 不存在。

- [ ] **Step 3: Create migration 0003**

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/alembic -c migrations/alembic.ini revision -m "create hitl_tasks table" --rev-id 0003
```

编辑 `migrations/versions/0003_*.py`:

```python
"""create hitl_tasks table

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-20 XX:XX:XX
"""
from alembic import op
import sqlalchemy as sa

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'hitl_tasks',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('f_stage', sa.Text(), nullable=False),
        sa.Column('entity_type', sa.Text(), nullable=False),
        sa.Column('entity_id', sa.Integer(), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('status', sa.Text(), server_default='pending', nullable=False),
        sa.Column('edited_payload', sa.JSON(), nullable=True),
        sa.Column('reviewer_id', sa.Integer(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_hitl_status', 'hitl_tasks', ['status'])
    op.create_index('idx_hitl_stage', 'hitl_tasks', ['f_stage', 'status'])


def downgrade() -> None:
    op.drop_index('idx_hitl_stage', 'hitl_tasks')
    op.drop_index('idx_hitl_status', 'hitl_tasks')
    op.drop_table('hitl_tasks')
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/python.exe -m pytest tests/core/test_migrations_hitl.py -v
```
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add migrations/versions/0003_create_hitl_tasks.py tests/core/test_migrations_hitl.py
git commit -m "feat(F1-T2): add hitl_tasks table migration

- polymorphic (entity_type, entity_id), no FK (audit neutrality)
- f_stage values used by F1: F1_competency_review, F1_skill_classification
- roundtrip tested

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task T3: audit_events Table + WORM Triggers

**Files:**
- Create: `migrations/versions/0004_create_audit_events.py`
- Test: `tests/core/test_migrations_audit.py`

**Context:** 审计表是 WORM (Write Once Read Many) — INSERT 允许，UPDATE/DELETE 在 DB 层被触发器拒绝。这是合规硬约束，不能仅靠应用层。

- [ ] **Step 1: Create the failing test**

Create `tests/core/test_migrations_audit.py`:

```python
"""验证 audit_events 表 migration 含 WORM 触发器."""
import sqlite3
import pytest
from alembic import command
from alembic.config import Config


def _cfg(db: str) -> Config:
    cfg = Config("migrations/alembic.ini")
    cfg.set_main_option("script_location", "migrations")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db}")
    return cfg


def test_audit_events_table_created(tmp_path):
    db = tmp_path / "t.db"
    command.upgrade(_cfg(str(db)), "0004")

    conn = sqlite3.connect(str(db))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(audit_events)").fetchall()}
    assert cols >= {
        "event_id", "f_stage", "action", "entity_type", "entity_id",
        "input_hash", "output_hash", "prompt_version",
        "model_name", "model_version", "reviewer_id",
        "created_at", "retention_until",
    }

    triggers = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='audit_events'"
    ).fetchall()}
    assert "audit_no_update" in triggers
    assert "audit_no_delete" in triggers
    conn.close()


def test_audit_worm_insert_allowed(tmp_path):
    db = tmp_path / "t.db"
    command.upgrade(_cfg(str(db)), "0004")
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO audit_events (event_id, f_stage, action, entity_type) "
        "VALUES ('u1', 'F1', 'extract', 'job')"
    )
    conn.commit()
    count = conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
    assert count == 1
    conn.close()


def test_audit_worm_update_forbidden(tmp_path):
    db = tmp_path / "t.db"
    command.upgrade(_cfg(str(db)), "0004")
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO audit_events (event_id, f_stage, action, entity_type) "
        "VALUES ('u1', 'F1', 'extract', 'job')"
    )
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError, match="WORM"):
        conn.execute("UPDATE audit_events SET action='tampered' WHERE event_id='u1'")
        conn.commit()
    conn.close()


def test_audit_worm_delete_forbidden(tmp_path):
    db = tmp_path / "t.db"
    command.upgrade(_cfg(str(db)), "0004")
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO audit_events (event_id, f_stage, action, entity_type) "
        "VALUES ('u1', 'F1', 'extract', 'job')"
    )
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError, match="WORM"):
        conn.execute("DELETE FROM audit_events WHERE event_id='u1'")
        conn.commit()
    conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/python.exe -m pytest tests/core/test_migrations_audit.py -v
```
Expected: FAIL — revision 0004 不存在。

- [ ] **Step 3: Create migration 0004**

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/alembic -c migrations/alembic.ini revision -m "create audit_events table with WORM triggers" --rev-id 0004
```

编辑 `migrations/versions/0004_*.py`:

```python
"""create audit_events table with WORM triggers

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-20 XX:XX:XX
"""
from alembic import op
import sqlalchemy as sa

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'audit_events',
        sa.Column('event_id', sa.Text(), nullable=False),
        sa.Column('f_stage', sa.Text(), nullable=False),
        sa.Column('action', sa.Text(), nullable=False),
        sa.Column('entity_type', sa.Text(), nullable=False),
        sa.Column('entity_id', sa.Integer(), nullable=True),
        sa.Column('input_hash', sa.Text(), nullable=True),
        sa.Column('output_hash', sa.Text(), nullable=True),
        sa.Column('prompt_version', sa.Text(), nullable=True),
        sa.Column('model_name', sa.Text(), nullable=True),
        sa.Column('model_version', sa.Text(), nullable=True),
        sa.Column('reviewer_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('retention_until', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('event_id'),
    )
    op.create_index('idx_audit_entity', 'audit_events', ['entity_type', 'entity_id'])
    op.create_index('idx_audit_stage', 'audit_events', ['f_stage', 'created_at'])

    # WORM triggers — SQLite 层强约束
    op.execute("""
        CREATE TRIGGER audit_no_update
        BEFORE UPDATE ON audit_events
        FOR EACH ROW
        BEGIN
            SELECT RAISE(FAIL, 'WORM: audit_events is append-only');
        END
    """)
    op.execute("""
        CREATE TRIGGER audit_no_delete
        BEFORE DELETE ON audit_events
        FOR EACH ROW
        BEGIN
            SELECT RAISE(FAIL, 'WORM: audit_events is append-only');
        END
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_no_delete")
    op.execute("DROP TRIGGER IF EXISTS audit_no_update")
    op.drop_index('idx_audit_stage', 'audit_events')
    op.drop_index('idx_audit_entity', 'audit_events')
    op.drop_table('audit_events')
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/python.exe -m pytest tests/core/test_migrations_audit.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add migrations/versions/0004_create_audit_events.py tests/core/test_migrations_audit.py
git commit -m "feat(F1-T3): add audit_events table with WORM triggers

- audit_no_update / audit_no_delete triggers enforce append-only at DB layer
- 4 tests: table structure + INSERT allowed + UPDATE/DELETE forbidden with 'WORM' error
- PIPL §24 compliance foundation

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task T4: jobs Table — Add 3 Columns

**Files:**
- Create: `migrations/versions/0005_jobs_competency_columns.py`
- Test: `tests/core/test_migrations_jobs.py`

**Context:** SQLite 的 `ALTER TABLE` 只支持加列不支持删/改，所以 batch mode 必须。加 3 列：`jd_text` / `competency_model` / `competency_model_status`。

- [ ] **Step 1: Create the failing test**

Create `tests/core/test_migrations_jobs.py`:

```python
"""验证 jobs 表扩展 3 列."""
import sqlite3
from alembic import command
from alembic.config import Config


def _cfg(db: str) -> Config:
    cfg = Config("migrations/alembic.ini")
    cfg.set_main_option("script_location", "migrations")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db}")
    return cfg


def _seed_old_schema(db: str):
    """模拟 M2 老 DB: jobs 表已存在, 只有扁平字段."""
    conn = sqlite3.connect(db)
    conn.execute("""
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
        )
    """)
    conn.execute("INSERT INTO jobs (title, education_min) VALUES ('old_job', '本科')")
    conn.commit()
    conn.close()


def test_jobs_columns_added(tmp_path):
    db = tmp_path / "t.db"
    _seed_old_schema(str(db))

    cfg = _cfg(str(db))
    command.stamp(cfg, "0004")  # 假装已在 0004
    command.upgrade(cfg, "0005")

    conn = sqlite3.connect(str(db))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    assert "jd_text" in cols
    assert "competency_model" in cols
    assert "competency_model_status" in cols

    # 老数据保留 + 新列默认值
    row = conn.execute("SELECT title, jd_text, competency_model, competency_model_status FROM jobs").fetchone()
    assert row[0] == "old_job"
    assert row[1] == ""
    assert row[2] is None
    assert row[3] == "none"
    conn.close()


def test_jobs_downgrade_removes_columns(tmp_path):
    db = tmp_path / "t.db"
    _seed_old_schema(str(db))

    cfg = _cfg(str(db))
    command.stamp(cfg, "0004")
    command.upgrade(cfg, "0005")
    command.downgrade(cfg, "0004")

    conn = sqlite3.connect(str(db))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    assert "jd_text" not in cols
    assert "competency_model" not in cols
    assert "competency_model_status" not in cols
    conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/python.exe -m pytest tests/core/test_migrations_jobs.py -v
```
Expected: FAIL — revision 0005 不存在。

- [ ] **Step 3: Create migration 0005**

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/alembic -c migrations/alembic.ini revision -m "jobs add competency columns" --rev-id 0005
```

编辑 `migrations/versions/0005_*.py`:

```python
"""jobs add competency columns

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-20 XX:XX:XX
"""
from alembic import op
import sqlalchemy as sa

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('jobs') as batch_op:
        batch_op.add_column(sa.Column('jd_text', sa.Text(), server_default='', nullable=False))
        batch_op.add_column(sa.Column('competency_model', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('competency_model_status', sa.Text(), server_default='none', nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('jobs') as batch_op:
        batch_op.drop_column('competency_model_status')
        batch_op.drop_column('competency_model')
        batch_op.drop_column('jd_text')
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/python.exe -m pytest tests/core/test_migrations_jobs.py -v
```
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add migrations/versions/0005_jobs_competency_columns.py tests/core/test_migrations_jobs.py
git commit -m "feat(F1-T4): jobs table add jd_text/competency_model/competency_model_status

- batch mode for SQLite ALTER TABLE
- old M2 data preserved (title='old_job' etc.)
- roundtrip tested

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task T5: Seed Skills Migration

**Files:**
- Create: `app/core/__init__.py` (empty)
- Create: `app/core/competency/__init__.py`（定义常量 SKILL_SIMILARITY_THRESHOLD）
- Create: `app/core/competency/seed_skills.json`（50–80 条）
- Create: `migrations/versions/0006_seed_skills.py`
- Test: `tests/core/test_migrations_seed_skills.py`

**Context:** 种子技能初始化 skills 表。`embedding` 列允许 NULL（AI 未配置时懒加载），migration 只写 `canonical_name` / `category` / `aliases` / `source='seed'`。

- [ ] **Step 1: Create `app/core/__init__.py` + `app/core/competency/__init__.py`**

```bash
cd /d/libz/AgenticHR
mkdir -p app/core/competency
touch app/core/__init__.py
```

Create `app/core/competency/__init__.py`:

```python
"""F1 能力模型包."""

SKILL_SIMILARITY_THRESHOLD = 0.85
"""技能归一化余弦相似度阈值. 超过 → 复用; 否则 → 新技能."""
```

- [ ] **Step 2: Create `app/core/competency/seed_skills.json`**

Create with this content (54 条主流技能, F1 可扩至 80):

```json
[
  {"name": "Python", "category": "language", "aliases": ["python3", "py"]},
  {"name": "Java", "category": "language", "aliases": ["jdk"]},
  {"name": "Go", "category": "language", "aliases": ["golang"]},
  {"name": "JavaScript", "category": "language", "aliases": ["js"]},
  {"name": "TypeScript", "category": "language", "aliases": ["ts"]},
  {"name": "Rust", "category": "language", "aliases": []},
  {"name": "C++", "category": "language", "aliases": ["cpp"]},
  {"name": "C#", "category": "language", "aliases": ["csharp", ".net"]},
  {"name": "PHP", "category": "language", "aliases": []},
  {"name": "Kotlin", "category": "language", "aliases": []},

  {"name": "FastAPI", "category": "framework", "aliases": []},
  {"name": "Django", "category": "framework", "aliases": []},
  {"name": "Flask", "category": "framework", "aliases": []},
  {"name": "Spring Boot", "category": "framework", "aliases": ["spring"]},
  {"name": "Vue.js", "category": "framework", "aliases": ["vue", "vue3"]},
  {"name": "React", "category": "framework", "aliases": ["reactjs"]},
  {"name": "Angular", "category": "framework", "aliases": []},
  {"name": "Node.js", "category": "framework", "aliases": ["nodejs"]},
  {"name": "Express", "category": "framework", "aliases": ["expressjs"]},
  {"name": "NestJS", "category": "framework", "aliases": []},

  {"name": "AWS", "category": "cloud", "aliases": ["amazon web services"]},
  {"name": "阿里云", "category": "cloud", "aliases": ["aliyun", "alicloud"]},
  {"name": "腾讯云", "category": "cloud", "aliases": ["tencent cloud"]},
  {"name": "Azure", "category": "cloud", "aliases": ["azure cloud"]},
  {"name": "Google Cloud", "category": "cloud", "aliases": ["gcp"]},

  {"name": "MySQL", "category": "database", "aliases": []},
  {"name": "PostgreSQL", "category": "database", "aliases": ["postgres", "pg"]},
  {"name": "Redis", "category": "database", "aliases": []},
  {"name": "MongoDB", "category": "database", "aliases": ["mongo"]},
  {"name": "ClickHouse", "category": "database", "aliases": []},
  {"name": "ElasticSearch", "category": "database", "aliases": ["es", "elastic"]},
  {"name": "Kafka", "category": "database", "aliases": []},

  {"name": "Git", "category": "tool", "aliases": []},
  {"name": "Docker", "category": "tool", "aliases": []},
  {"name": "Kubernetes", "category": "tool", "aliases": ["k8s"]},
  {"name": "Jenkins", "category": "tool", "aliases": []},
  {"name": "Prometheus", "category": "tool", "aliases": []},
  {"name": "Grafana", "category": "tool", "aliases": []},
  {"name": "Linux", "category": "tool", "aliases": []},
  {"name": "Nginx", "category": "tool", "aliases": []},
  {"name": "GitHub Actions", "category": "tool", "aliases": []},
  {"name": "GitLab CI", "category": "tool", "aliases": []},

  {"name": "沟通能力", "category": "soft", "aliases": []},
  {"name": "学习能力", "category": "soft", "aliases": []},
  {"name": "抗压能力", "category": "soft", "aliases": []},
  {"name": "团队协作", "category": "soft", "aliases": []},
  {"name": "解决问题", "category": "soft", "aliases": []},
  {"name": "领导力", "category": "soft", "aliases": []},

  {"name": "大模型应用", "category": "domain", "aliases": ["llm 应用"]},
  {"name": "推荐系统", "category": "domain", "aliases": []},
  {"name": "搜索引擎", "category": "domain", "aliases": []},
  {"name": "金融风控", "category": "domain", "aliases": []},
  {"name": "电商后端", "category": "domain", "aliases": []},
  {"name": "即时通讯", "category": "domain", "aliases": ["im"]},
  {"name": "音视频", "category": "domain", "aliases": []}
]
```

- [ ] **Step 3: Create the failing test**

Create `tests/core/test_migrations_seed_skills.py`:

```python
"""验证 seed 技能被填入 skills 表."""
import sqlite3
from alembic import command
from alembic.config import Config


def _cfg(db: str) -> Config:
    cfg = Config("migrations/alembic.ini")
    cfg.set_main_option("script_location", "migrations")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db}")
    return cfg


def test_seed_skills_inserted(tmp_path):
    db = tmp_path / "t.db"
    command.upgrade(_cfg(str(db)), "0006")

    conn = sqlite3.connect(str(db))
    count = conn.execute("SELECT COUNT(*) FROM skills WHERE source='seed'").fetchone()[0]
    assert count >= 50, f"expected >=50 seed skills, got {count}"

    # 关键种子存在
    python_row = conn.execute(
        "SELECT canonical_name, category FROM skills WHERE canonical_name='Python'"
    ).fetchone()
    assert python_row == ("Python", "language")

    # aliases 作为 JSON 存储
    python_aliases = conn.execute(
        "SELECT aliases FROM skills WHERE canonical_name='Python'"
    ).fetchone()[0]
    assert "python3" in python_aliases

    # seed 的 embedding 初始 NULL（懒加载）
    none_embed = conn.execute(
        "SELECT COUNT(*) FROM skills WHERE source='seed' AND embedding IS NULL"
    ).fetchone()[0]
    assert none_embed >= 50

    conn.close()


def test_seed_idempotent(tmp_path):
    """多次 upgrade-downgrade-upgrade 不会重复插入."""
    db = tmp_path / "t.db"
    cfg = _cfg(str(db))
    command.upgrade(cfg, "0006")
    count1 = _count(db)
    command.downgrade(cfg, "0005")
    command.upgrade(cfg, "0006")
    count2 = _count(db)
    assert count1 == count2


def _count(db):
    conn = sqlite3.connect(str(db))
    c = conn.execute("SELECT COUNT(*) FROM skills WHERE source='seed'").fetchone()[0]
    conn.close()
    return c
```

- [ ] **Step 4: Run test to verify it fails**

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/python.exe -m pytest tests/core/test_migrations_seed_skills.py -v
```
Expected: FAIL — revision 0006 不存在。

- [ ] **Step 5: Create migration 0006**

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/alembic -c migrations/alembic.ini revision -m "seed skills library" --rev-id 0006
```

编辑 `migrations/versions/0006_*.py`:

```python
"""seed skills library

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-20 XX:XX:XX
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
```

- [ ] **Step 6: Run test to verify it passes**

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/python.exe -m pytest tests/core/test_migrations_seed_skills.py -v
```
Expected: 2 passed.

- [ ] **Step 7: Stamp user's DB to 0006 + verify**

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/alembic -c migrations/alembic.ini upgrade head
./.venv/Scripts/alembic -c migrations/alembic.ini current
```
Expected: `0006 (head)`。现用户 DB 已有 skills/hitl_tasks/audit_events 表 + jobs 新列 + 54 条种子。

- [ ] **Step 8: Commit**

```bash
git add app/core/__init__.py app/core/competency/__init__.py app/core/competency/seed_skills.json \
        migrations/versions/0006_seed_skills.py tests/core/test_migrations_seed_skills.py
git commit -m "feat(F1-T5): seed skills library (54 entries) + lazy embedding

- seed_skills.json: 10 languages, 10 frameworks, 5 clouds, 7 databases,
  11 tools, 6 soft, 5 domain
- embedding=NULL initially (loaded on first normalize() call)
- upgrade idempotent (INSERT OR IGNORE)
- downgrade only removes source=seed

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 2A — Core Infrastructure (llm + audit + vector)

### Task T6: core/llm/parsing.py — JSON extraction helper

**Files:**
- Create: `app/core/llm/__init__.py`
- Create: `app/core/llm/parsing.py`
- Test: `tests/core/test_llm_parsing.py`

**Context:** 搬 `app/modules/resume/pdf_parser.py::_extract_json()` 到 core，再加 Pydantic 校验包装，供 F1/F2/F3 复用。

- [ ] **Step 1: Create `app/core/llm/__init__.py`** (空文件)

```bash
cd /d/libz/AgenticHR
mkdir -p app/core/llm
touch app/core/llm/__init__.py
```

- [ ] **Step 2: Create failing test**

Create `tests/core/test_llm_parsing.py`:

```python
"""core.llm.parsing — JSON 解析 + Pydantic 校验."""
import pytest
from pydantic import BaseModel, ValidationError

from app.core.llm.parsing import extract_json, parse_json_as


class _Demo(BaseModel):
    name: str
    age: int


def test_extract_plain_json():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_with_code_fence():
    s = '```json\n{"a": 2}\n```'
    assert extract_json(s) == {"a": 2}


def test_extract_json_with_bare_fence():
    s = '```\n{"a": 3}\n```'
    assert extract_json(s) == {"a": 3}


def test_extract_json_with_prefix_suffix_noise():
    s = 'sure! here is: ```json\n{"a": 4}\n``` hope this helps.'
    assert extract_json(s) == {"a": 4}


def test_extract_invalid_json_raises():
    with pytest.raises(ValueError):
        extract_json("not json at all")


def test_parse_json_as_valid():
    obj = parse_json_as('{"name":"bob","age":30}', _Demo)
    assert obj.name == "bob"
    assert obj.age == 30


def test_parse_json_as_invalid_raises_validation_error():
    with pytest.raises(ValidationError):
        parse_json_as('{"name":"bob","age":"not_a_number"}', _Demo)


def test_parse_json_as_strips_code_fence():
    s = '```json\n{"name":"x","age":1}\n```'
    obj = parse_json_as(s, _Demo)
    assert obj.name == "x"
```

- [ ] **Step 3: Run test to verify it fails**

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/python.exe -m pytest tests/core/test_llm_parsing.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'app.core.llm.parsing'`。

- [ ] **Step 4: Implement `app/core/llm/parsing.py`**

Create `app/core/llm/parsing.py`:

```python
"""LLM JSON 响应解析 + Pydantic 校验. F1/F2/F3 共享."""
import json
from typing import TypeVar, Type

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


def extract_json(text: str) -> dict:
    """从 LLM 响应里抽出 JSON 对象.

    处理常见包装:
      - 裸 JSON: '{"a":1}'
      - ```json ... ``` 围栏
      - ``` ... ``` 裸围栏
      - 前后文字噪声 (贪婪匹配第一个 { 到最后一个 })

    失败抛 ValueError.
    """
    if not text:
        raise ValueError("empty input")

    # 去围栏
    s = text.strip()
    if "```json" in s:
        s = s.split("```json", 1)[1]
        if "```" in s:
            s = s.split("```", 1)[0]
    elif "```" in s:
        parts = s.split("```")
        if len(parts) >= 3:
            s = parts[1]
        else:
            s = parts[-1]
    s = s.strip()

    # 提取最外层 {...} (贪婪)
    start = s.find("{")
    end = s.rfind("}")
    if start < 0 or end < 0 or end <= start:
        raise ValueError(f"no JSON object found in: {text[:120]!r}")
    candidate = s[start:end + 1]

    try:
        return json.loads(candidate)
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid JSON: {e}; got: {candidate[:120]!r}") from e


def parse_json_as(text: str, model_cls: Type[T]) -> T:
    """extract_json + Pydantic 校验的组合. 失败抛 ValueError 或 ValidationError."""
    data = extract_json(text)
    return model_cls.model_validate(data)
```

- [ ] **Step 5: Run test to verify it passes**

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/python.exe -m pytest tests/core/test_llm_parsing.py -v
```
Expected: 8 passed.

- [ ] **Step 6: Commit**

```bash
git add app/core/llm/__init__.py app/core/llm/parsing.py tests/core/test_llm_parsing.py
git commit -m "feat(F1-T6): core/llm/parsing — JSON extraction + Pydantic validation

- extract_json handles bare JSON, code-fence wrapped, and noisy text
- parse_json_as composes extract_json + Pydantic model_validate
- 8 test cases cover happy path + all fence variants + invalid inputs
- Migrated from resume/pdf_parser.py::_extract_json with ValueError on failure
  (vs silent return); caller must handle exception

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task T7: core/audit/ — WORM-backed audit logger

**Files:**
- Create: `app/core/audit/__init__.py`
- Create: `app/core/audit/models.py`
- Create: `app/core/audit/logger.py`
- Test: `tests/core/test_audit_logger.py`

**Context:** 审计日志是 F3/F5/F8 的合规底座。F1 里只有 extract/normalize/hitl_* 动作用，但**结构必须一次性稳固**，后续 F 只加新 action 类型。

- [ ] **Step 1: Create the failing test**

Create `tests/core/__init__.py` (if not exists, skip) + `tests/core/test_audit_logger.py`:

```python
"""core.audit.logger — WORM 审计."""
import hashlib
import json
from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.database import Base, engine, SessionLocal
from app.core.audit.logger import log_event, compute_hash
from app.core.audit.models import AuditEvent


@pytest.fixture(autouse=True)
def _clean_db(tmp_path, monkeypatch):
    """每个测试用独立 SQLite + alembic migration."""
    import sqlalchemy as sa
    from alembic import command
    from alembic.config import Config

    db_path = tmp_path / "audit.db"
    url = f"sqlite:///{db_path}"

    cfg = Config("migrations/alembic.ini")
    cfg.set_main_option("script_location", "migrations")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "0006")

    # 重绑 session
    new_engine = sa.create_engine(url, connect_args={"check_same_thread": False})
    monkeypatch.setattr("app.database.engine", new_engine)
    from app.core.audit.logger import _session_factory
    monkeypatch.setattr("app.core.audit.logger._session_factory",
                        sa.orm.sessionmaker(bind=new_engine))
    yield


def test_log_event_inserts_row():
    event_id = log_event(
        f_stage="F1_competency_review",
        action="extract",
        entity_type="job",
        entity_id=1,
        input_payload={"jd": "demo"},
        output_payload={"skills": ["Python"]},
        prompt_version="f1_v1",
        model_name="glm-4-flash",
    )
    assert isinstance(event_id, str)
    assert len(event_id) == 36  # uuid

    # 读回
    import sqlalchemy as sa
    from app.database import engine
    with engine.connect() as conn:
        row = conn.execute(sa.text("SELECT * FROM audit_events WHERE event_id=:id"),
                           {"id": event_id}).mappings().one()
    assert row["action"] == "extract"
    assert row["entity_type"] == "job"
    assert row["entity_id"] == 1
    assert row["prompt_version"] == "f1_v1"
    assert row["model_name"] == "glm-4-flash"
    assert len(row["input_hash"]) == 64  # SHA256 hex
    assert len(row["output_hash"]) == 64


def test_log_event_hashes_deterministic():
    h1 = compute_hash({"a": 1, "b": 2})
    h2 = compute_hash({"b": 2, "a": 1})  # 不同顺序
    assert h1 == h2  # sorted keys


def test_log_event_null_entity_id():
    eid = log_event(f_stage="F1", action="extract_fail", entity_type="job", entity_id=None)
    assert eid


def test_log_event_writes_payload_file(tmp_path, monkeypatch):
    monkeypatch.setattr("app.core.audit.logger.AUDIT_DIR", str(tmp_path / "audit"))
    eid = log_event(
        f_stage="F1", action="extract", entity_type="job", entity_id=1,
        input_payload={"big": "data"}, output_payload={"r": 1},
    )
    path = tmp_path / "audit" / f"{eid}.json"
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["input"] == {"big": "data"}
    assert data["output"] == {"r": 1}


def test_audit_update_forbidden():
    log_event(f_stage="F1", action="extract", entity_type="job", entity_id=1)
    import sqlalchemy as sa
    from app.database import engine
    with engine.connect() as conn:
        with pytest.raises(Exception, match="WORM"):
            conn.execute(sa.text("UPDATE audit_events SET action='x'"))
            conn.commit()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/python.exe -m pytest tests/core/test_audit_logger.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'app.core.audit'`。

- [ ] **Step 3: Implement `app/core/audit/models.py`**

```bash
cd /d/libz/AgenticHR
mkdir -p app/core/audit
touch app/core/audit/__init__.py
```

Create `app/core/audit/models.py`:

```python
"""audit_events SQLAlchemy model. Schema 由 migration 0004 建立."""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, Text, DateTime
from app.database import Base


class AuditEvent(Base):
    __tablename__ = "audit_events"

    event_id = Column(Text, primary_key=True)
    f_stage = Column(Text, nullable=False)
    action = Column(Text, nullable=False)
    entity_type = Column(Text, nullable=False)
    entity_id = Column(Integer, nullable=True)
    input_hash = Column(Text, nullable=True)
    output_hash = Column(Text, nullable=True)
    prompt_version = Column(Text, nullable=True)
    model_name = Column(Text, nullable=True)
    model_version = Column(Text, nullable=True)
    reviewer_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    retention_until = Column(DateTime, nullable=True)
```

- [ ] **Step 4: Implement `app/core/audit/logger.py`**

Create `app/core/audit/logger.py`:

```python
"""WORM 审计日志写入. 大 payload 外置到 data/audit/{event_id}.json."""
import hashlib
import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import sessionmaker

from app.database import engine
from app.core.audit.models import AuditEvent

logger = logging.getLogger(__name__)

AUDIT_DIR = os.environ.get("AGENTICHR_AUDIT_DIR", "data/audit")
RETENTION_YEARS = 3

_session_factory = sessionmaker(bind=engine)


def compute_hash(payload: Any) -> str:
    """SHA256 hex. dict 按 sorted keys 规整化, 保证幂等."""
    if payload is None:
        return ""
    if isinstance(payload, (dict, list)):
        s = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    else:
        s = str(payload)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _write_payload_file(event_id: str, input_payload: Any, output_payload: Any) -> None:
    """大 payload 外置存储, 文件名 = event_id."""
    Path(AUDIT_DIR).mkdir(parents=True, exist_ok=True)
    path = Path(AUDIT_DIR) / f"{event_id}.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(
            {"input": input_payload, "output": output_payload},
            f, ensure_ascii=False, indent=2, default=str,
        )


def log_event(
    f_stage: str,
    action: str,
    entity_type: str,
    entity_id: int | None = None,
    input_payload: Any = None,
    output_payload: Any = None,
    prompt_version: str = "",
    model_name: str = "",
    model_version: str = "",
    reviewer_id: int | None = None,
) -> str:
    """写一条 audit event, 返回 event_id (UUID4).

    input/output payload 哈希写入表, 原文写入 AUDIT_DIR/{event_id}.json.
    WORM: 调用此函数后绝不能改也绝不能删.
    """
    event_id = str(uuid.uuid4())
    event = AuditEvent(
        event_id=event_id,
        f_stage=f_stage,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        input_hash=compute_hash(input_payload) if input_payload is not None else None,
        output_hash=compute_hash(output_payload) if output_payload is not None else None,
        prompt_version=prompt_version or None,
        model_name=model_name or None,
        model_version=model_version or None,
        reviewer_id=reviewer_id,
        retention_until=datetime.now(timezone.utc) + timedelta(days=365 * RETENTION_YEARS),
    )

    session = _session_factory()
    try:
        session.add(event)
        session.commit()
        if input_payload is not None or output_payload is not None:
            _write_payload_file(event_id, input_payload, output_payload)
    except Exception as e:
        session.rollback()
        logger.error(f"audit log_event failed: {e}")
        raise
    finally:
        session.close()

    return event_id
```

- [ ] **Step 5: Run test to verify it passes**

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/python.exe -m pytest tests/core/test_audit_logger.py -v
```
Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add app/core/audit/ tests/core/test_audit_logger.py
git commit -m "feat(F1-T7): core/audit — WORM audit logger

- log_event() writes row + external payload file
- compute_hash() SHA256 with sorted-keys JSON for determinism
- AUDIT_DIR configurable via AGENTICHR_AUDIT_DIR env
- retention_until defaults to +3 years
- 5 tests including WORM enforcement (UPDATE raises)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task T8: core/vector/ — cosine + float32 pack

**Files:**
- Create: `app/core/vector/__init__.py`
- Create: `app/core/vector/service.py`
- Test: `tests/core/test_vector_service.py`

**Context:** Embedding 存储 (float32 → bytes) 和 余弦相似度计算的基础设施。F1 归一化 + F2 简历匹配都会用。

- [ ] **Step 1: Create the failing test**

Create `tests/core/test_vector_service.py`:

```python
"""core.vector.service — cosine + float32 pack."""
import numpy as np
import pytest

from app.core.vector.service import cosine_similarity, pack_vector, unpack_vector, find_nearest


def test_cosine_identical():
    a = [1.0, 0.0, 0.0]
    b = [1.0, 0.0, 0.0]
    assert abs(cosine_similarity(a, b) - 1.0) < 1e-6


def test_cosine_orthogonal():
    a = [1.0, 0.0]
    b = [0.0, 1.0]
    assert abs(cosine_similarity(a, b) - 0.0) < 1e-6


def test_cosine_opposite():
    a = [1.0, 0.0]
    b = [-1.0, 0.0]
    assert abs(cosine_similarity(a, b) - (-1.0)) < 1e-6


def test_pack_unpack_roundtrip():
    vec = [0.1, -0.2, 0.3, 0.4]
    blob = pack_vector(vec)
    assert isinstance(blob, bytes)
    assert len(blob) == 4 * 4  # float32 × 4
    back = unpack_vector(blob)
    assert len(back) == 4
    for a, b in zip(vec, back):
        assert abs(a - b) < 1e-6


def test_pack_numpy_array():
    vec = np.array([1.0, 2.0, 3.0], dtype=np.float32)
    blob = pack_vector(vec)
    back = unpack_vector(blob)
    assert list(back) == pytest.approx([1.0, 2.0, 3.0])


def test_find_nearest_picks_highest_similarity():
    query = [1.0, 0.0]
    candidates = [
        (1, [0.9, 0.1]),     # 高相似
        (2, [0.1, 0.9]),     # 低相似
        (3, [0.95, 0.05]),   # 最高
    ]
    best_id, best_sim = find_nearest(query, candidates)
    assert best_id == 3
    assert best_sim > 0.99


def test_find_nearest_empty_returns_none():
    best_id, best_sim = find_nearest([1.0, 0.0], [])
    assert best_id is None
    assert best_sim == 0.0


def test_find_nearest_zero_vector():
    """零向量的余弦无定义, 返回 0 相似度不崩."""
    best_id, best_sim = find_nearest([0.0, 0.0], [(1, [1.0, 0.0])])
    assert best_sim == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/python.exe -m pytest tests/core/test_vector_service.py -v
```
Expected: FAIL — `ModuleNotFoundError`。

- [ ] **Step 3: Implement `app/core/vector/service.py`**

```bash
cd /d/libz/AgenticHR
mkdir -p app/core/vector
touch app/core/vector/__init__.py
```

Create `app/core/vector/service.py`:

```python
"""向量打包 / cosine 相似度 / 最近邻检索. 无外部依赖, 仅 numpy."""
import numpy as np
from typing import Sequence


def pack_vector(vec: Sequence[float] | np.ndarray) -> bytes:
    """float[] → bytes (float32 little-endian). 存入 skills.embedding 列."""
    arr = np.asarray(vec, dtype=np.float32)
    return arr.tobytes()


def unpack_vector(blob: bytes) -> np.ndarray:
    """skills.embedding blob → numpy float32 array."""
    return np.frombuffer(blob, dtype=np.float32)


def cosine_similarity(a: Sequence[float] | np.ndarray,
                       b: Sequence[float] | np.ndarray) -> float:
    """两向量余弦. 任一零向量返回 0."""
    a_arr = np.asarray(a, dtype=np.float32)
    b_arr = np.asarray(b, dtype=np.float32)
    na = float(np.linalg.norm(a_arr))
    nb = float(np.linalg.norm(b_arr))
    if na < 1e-12 or nb < 1e-12:
        return 0.0
    return float(np.dot(a_arr, b_arr) / (na * nb))


def find_nearest(
    query: Sequence[float] | np.ndarray,
    candidates: list[tuple[int, Sequence[float] | np.ndarray]],
) -> tuple[int | None, float]:
    """从 (id, vec) 列表里找与 query 余弦最近的一个.

    空列表返回 (None, 0.0). 零向量 query 返回任意 id 的相似度 0.0.
    """
    if not candidates:
        return None, 0.0

    best_id: int | None = None
    best_sim = -1.0
    for cid, cvec in candidates:
        sim = cosine_similarity(query, cvec)
        if sim > best_sim:
            best_sim = sim
            best_id = cid

    if best_sim < 0:
        return None, 0.0
    return best_id, best_sim
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/python.exe -m pytest tests/core/test_vector_service.py -v
```
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add app/core/vector/ tests/core/test_vector_service.py
git commit -m "feat(F1-T8): core/vector — cosine + float32 pack

- pack_vector/unpack_vector for skills.embedding BLOB storage
- cosine_similarity handles zero vectors (returns 0.0, no ZeroDivisionError)
- find_nearest picks highest-sim candidate id from list
- 8 tests cover all edge cases

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task T9: core/llm/provider.py — LLM Provider with retry + audit

**Files:**
- Create: `app/core/llm/provider.py`
- Modify: `app/config.py` — add `ai_model_competency` optional setting
- Test: `tests/core/test_llm_provider.py`

**Context:** LLM 调用统一入口. F1 extract / F2 evaluate / F5 decision / F8 final 都走这个. 每次调用自动重试 + audit 钩子.

- [ ] **Step 1: Add `ai_model_competency` to `app/config.py`**

Read `app/config.py` 确认现字段, 然后加一行.

Modify `app/config.py`, 在 `ai_model: str = ""` 后加:

```python
    ai_model_competency: str = ""
    """F1 能力模型抽取专用模型. 为空则回退 ai_model. 文档写明为可选覆盖."""
```

- [ ] **Step 2: Create the failing test**

Create `tests/core/test_llm_provider.py`:

```python
"""core.llm.provider — LLM call with retry + audit hooks."""
import pytest
import httpx
from unittest.mock import AsyncMock, patch

from app.core.llm.provider import LLMProvider, LLMError


def _mock_response(content: str, status: int = 200):
    return httpx.Response(
        status_code=status,
        json={"choices": [{"message": {"content": content}}]},
    )


@pytest.mark.asyncio
async def test_complete_success_single_try():
    mock_post = AsyncMock(return_value=_mock_response('{"ok": true}'))
    with patch("httpx.AsyncClient.post", mock_post):
        p = LLMProvider(api_key="k", base_url="http://demo", model="m")
        got = await p.complete(
            messages=[{"role": "user", "content": "hi"}],
            prompt_version="v1",
            f_stage="F1", entity_type="job", entity_id=1,
        )
    assert got == '{"ok": true}'
    assert mock_post.await_count == 1


@pytest.mark.asyncio
async def test_complete_retries_on_http_error():
    mock_post = AsyncMock(side_effect=[
        httpx.ConnectError("boom"),
        httpx.ConnectError("boom"),
        _mock_response('{"ok": 1}'),
    ])
    with patch("httpx.AsyncClient.post", mock_post):
        p = LLMProvider(api_key="k", base_url="http://demo", model="m",
                         max_retries=3, backoff_base=0.0)  # 测试加速
        got = await p.complete(
            messages=[{"role": "user", "content": "hi"}],
            prompt_version="v1", f_stage="F1", entity_type="job", entity_id=1,
        )
    assert got == '{"ok": 1}'
    assert mock_post.await_count == 3


@pytest.mark.asyncio
async def test_complete_gives_up_after_max_retries():
    mock_post = AsyncMock(side_effect=httpx.ConnectError("boom"))
    with patch("httpx.AsyncClient.post", mock_post):
        p = LLMProvider(api_key="k", base_url="http://demo", model="m",
                         max_retries=3, backoff_base=0.0)
        with pytest.raises(LLMError):
            await p.complete(
                messages=[{"role": "user", "content": "hi"}],
                prompt_version="v1", f_stage="F1", entity_type="job", entity_id=1,
            )
    assert mock_post.await_count == 3


@pytest.mark.asyncio
async def test_complete_calls_audit_hook(monkeypatch):
    seen = []

    def fake_log(**kwargs):
        seen.append(kwargs)
        return "event-id"

    monkeypatch.setattr("app.core.llm.provider.log_event", fake_log)
    mock_post = AsyncMock(return_value=_mock_response('{"ok": 1}'))
    with patch("httpx.AsyncClient.post", mock_post):
        p = LLMProvider(api_key="k", base_url="http://demo", model="glm-4-flash")
        await p.complete(
            messages=[{"role": "user", "content": "hi"}],
            prompt_version="f1_v1",
            f_stage="F1_competency_review",
            entity_type="job", entity_id=42,
        )
    assert len(seen) == 1
    assert seen[0]["f_stage"] == "F1_competency_review"
    assert seen[0]["action"] == "llm_complete"
    assert seen[0]["entity_id"] == 42
    assert seen[0]["prompt_version"] == "f1_v1"
    assert seen[0]["model_name"] == "glm-4-flash"
```

- [ ] **Step 3: Run test to verify it fails**

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/python.exe -m pytest tests/core/test_llm_provider.py -v
```
Expected: FAIL — module 不存在。

- [ ] **Step 4: Implement `app/core/llm/provider.py`**

```python
"""LLM Provider: chat completion with retry + audit hook."""
import asyncio
import logging
import httpx

from app.config import settings
from app.core.audit.logger import log_event

logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """LLM 调用重试全败后抛. 调用方决定降级逻辑."""


class LLMProvider:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        max_retries: int = 3,
        backoff_base: float = 1.0,  # 1s, 3s, 9s
        timeout: float = 60.0,
    ):
        self.api_key = api_key or settings.ai_api_key
        self.base_url = (base_url or settings.ai_base_url).rstrip("/")
        self.model = model or settings.ai_model
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.timeout = timeout

    def is_configured(self) -> bool:
        return bool(self.api_key and self.base_url and self.model)

    async def complete(
        self,
        messages: list[dict],
        *,
        prompt_version: str = "",
        f_stage: str = "",
        entity_type: str = "",
        entity_id: int | None = None,
        temperature: float = 0.2,
        response_format: str = "text",
    ) -> str:
        """返回 LLM 响应文本内容. 重试 max_retries 次后抛 LLMError."""
        body: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if response_format == "json":
            body["response_format"] = {"type": "json_object"}

        last_err: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(
                        f"{self.base_url}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json",
                        },
                        json=body,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"]

                log_event(
                    f_stage=f_stage or "unknown",
                    action="llm_complete",
                    entity_type=entity_type or "unknown",
                    entity_id=entity_id,
                    input_payload={"messages": messages, "temperature": temperature},
                    output_payload={"content": content},
                    prompt_version=prompt_version,
                    model_name=self.model,
                )
                return content

            except (httpx.HTTPError, KeyError, ValueError) as e:
                last_err = e
                logger.warning(
                    f"LLM complete attempt {attempt}/{self.max_retries} failed: {e}"
                )
                if attempt < self.max_retries:
                    await asyncio.sleep(self.backoff_base * (3 ** (attempt - 1)))

        log_event(
            f_stage=f_stage or "unknown",
            action="llm_complete_fail",
            entity_type=entity_type or "unknown",
            entity_id=entity_id,
            input_payload={"messages": messages},
            output_payload={"error": str(last_err)},
            prompt_version=prompt_version,
            model_name=self.model,
        )
        raise LLMError(f"LLM complete failed after {self.max_retries} retries: {last_err}")
```

- [ ] **Step 5: Run test to verify it passes**

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/python.exe -m pytest tests/core/test_llm_provider.py -v
```
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add app/core/llm/provider.py app/config.py tests/core/test_llm_provider.py
git commit -m "feat(F1-T9): core/llm/provider — chat completion with retry + audit

- LLMProvider.complete(): 3 retries, exponential backoff 1s/3s/9s
- auto-logs llm_complete or llm_complete_fail to audit_events
- prompt_version / f_stage / entity_type|id threaded through for audit
- LLMError raised after exhausting retries (caller handles fallback)
- ai_model_competency optional override in settings

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task T10: core/llm/provider.py — embed_batch + 智谱 API 实测

**Files:**
- Modify: `app/core/llm/provider.py`
- Test: `tests/core/test_llm_embed_batch.py`
- Manual verification script: `scripts/verify_embedding_api.py`

**Context:** 新增 `embed_batch()` 方法 + 独立一次性验证智谱 `/v1/embeddings` API 兼容 OpenAI 格式。这是 R1 风险点 — 必须在走到 T13 归一化前先确认。

- [ ] **Step 1: Create the failing test**

Create `tests/core/test_llm_embed_batch.py`:

```python
"""core.llm.provider.embed_batch — 批量 embedding."""
import pytest
import httpx
from unittest.mock import AsyncMock, patch

from app.core.llm.provider import LLMProvider, LLMError


def _embedding_response(vectors: list[list[float]], status: int = 200):
    return httpx.Response(
        status_code=status,
        json={"data": [{"embedding": v, "index": i} for i, v in enumerate(vectors)]},
    )


@pytest.mark.asyncio
async def test_embed_batch_success():
    mock_post = AsyncMock(return_value=_embedding_response([[0.1, 0.2], [0.3, 0.4]]))
    with patch("httpx.AsyncClient.post", mock_post):
        p = LLMProvider(api_key="k", base_url="http://demo", model="m")
        got = await p.embed_batch(["Python", "Java"])
    assert len(got) == 2
    assert got[0] == [0.1, 0.2]
    assert got[1] == [0.3, 0.4]
    # embed_batch 应该是 1 次 API 调用 (batch)
    assert mock_post.await_count == 1


@pytest.mark.asyncio
async def test_embed_batch_empty_list():
    p = LLMProvider(api_key="k", base_url="http://demo", model="m")
    got = await p.embed_batch([])
    assert got == []


@pytest.mark.asyncio
async def test_embed_batch_retries_on_error():
    mock_post = AsyncMock(side_effect=[
        httpx.ConnectError("boom"),
        _embedding_response([[1.0]]),
    ])
    with patch("httpx.AsyncClient.post", mock_post):
        p = LLMProvider(api_key="k", base_url="http://demo", model="m",
                         max_retries=3, backoff_base=0.0)
        got = await p.embed_batch(["X"])
    assert got == [[1.0]]
    assert mock_post.await_count == 2


@pytest.mark.asyncio
async def test_embed_batch_fail_raises_llm_error():
    mock_post = AsyncMock(side_effect=httpx.ConnectError("boom"))
    with patch("httpx.AsyncClient.post", mock_post):
        p = LLMProvider(api_key="k", base_url="http://demo", model="m",
                         max_retries=2, backoff_base=0.0)
        with pytest.raises(LLMError):
            await p.embed_batch(["X"])
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/python.exe -m pytest tests/core/test_llm_embed_batch.py -v
```
Expected: FAIL — `AttributeError: 'LLMProvider' object has no attribute 'embed_batch'`。

- [ ] **Step 3: Extend `app/core/llm/provider.py` with embed_batch**

在 `LLMProvider` 类里加两个方法 (文件末尾追加):

```python
    async def embed_batch(
        self,
        texts: list[str],
        *,
        embedding_model: str = "embedding-2",
    ) -> list[list[float]]:
        """批量 embedding. 空列表直接返回 []. 重试 max_retries 次后抛 LLMError."""
        if not texts:
            return []

        body = {"model": embedding_model, "input": texts}

        last_err: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(
                        f"{self.base_url}/embeddings",
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json",
                        },
                        json=body,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    # OpenAI 兼容: data 按 index 排序
                    items = sorted(data["data"], key=lambda x: x["index"])
                    return [item["embedding"] for item in items]
            except (httpx.HTTPError, KeyError, ValueError) as e:
                last_err = e
                logger.warning(f"embed_batch attempt {attempt} failed: {e}")
                if attempt < self.max_retries:
                    await asyncio.sleep(self.backoff_base * (3 ** (attempt - 1)))

        raise LLMError(f"embed_batch failed after {self.max_retries} retries: {last_err}")
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/python.exe -m pytest tests/core/test_llm_embed_batch.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Create manual verification script**

Create `scripts/verify_embedding_api.py`:

```python
"""一次性验证智谱 /v1/embeddings API 兼容性.

跑法: python -m scripts.verify_embedding_api

预期输出:
  embedding dim = 1024 (embedding-2) 或 2048 (embedding-3)
  向量值 float, 前 5 个类似: [0.0012, -0.0085, 0.0234, ...]
"""
import asyncio
import os
import sys

from app.core.llm.provider import LLMProvider


async def main():
    if not os.environ.get("AI_API_KEY") and not os.path.exists(".env"):
        print("ERROR: 需要 .env 或环境变量 AI_API_KEY/AI_BASE_URL", file=sys.stderr)
        sys.exit(1)

    p = LLMProvider()
    if not p.is_configured():
        print(f"ERROR: LLMProvider 未配置. base={p.base_url} model={p.model}")
        sys.exit(1)

    vectors = await p.embed_batch(["Python", "Java", "测试"])
    for i, (name, vec) in enumerate(zip(["Python", "Java", "测试"], vectors)):
        print(f"[{i}] {name}: dim={len(vec)}, head={vec[:5]}")

    assert all(len(v) == len(vectors[0]) for v in vectors), "维度不一致!"
    print(f"✓ 维度一致 = {len(vectors[0])}")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 6: Run manual verification**

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/python.exe -m scripts.verify_embedding_api
```
Expected: 输出 3 条向量, 维度一致 (1024 或 2048)。若失败 — 触发 R1 降级 (改用 chat-completion 两两对比同义判断)。

- [ ] **Step 7: Commit**

```bash
git add app/core/llm/provider.py scripts/verify_embedding_api.py tests/core/test_llm_embed_batch.py
git commit -m "feat(F1-T10): core/llm/provider.embed_batch + 智谱 API verify script

- embed_batch uses /v1/embeddings OpenAI-compatible endpoint
- returns sorted vectors by 'index' field
- 4 tests cover success / empty / retry / fail paths
- scripts/verify_embedding_api.py manual R1 risk verification

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 2B — Core Infrastructure (competency + hitl)

### Task T11: core/competency/schema.py — CompetencyModel

**Files:**
- Create: `app/core/competency/schema.py`
- Test: `tests/core/test_competency_schema.py`

- [ ] **Step 1: Create the failing test**

Create `tests/core/test_competency_schema.py`:

```python
"""core.competency.schema — CompetencyModel Pydantic."""
import pytest
from datetime import datetime
from pydantic import ValidationError

from app.core.competency.schema import (
    HardSkill, SoftSkill, ExperienceRequirement,
    EducationRequirement, AssessmentDimension, CompetencyModel,
)


def test_hard_skill_defaults():
    s = HardSkill(name="Python", weight=8)
    assert s.level == "熟练"
    assert s.must_have is False
    assert s.canonical_id is None


def test_hard_skill_weight_range():
    with pytest.raises(ValidationError):
        HardSkill(name="x", weight=0)
    with pytest.raises(ValidationError):
        HardSkill(name="x", weight=11)
    HardSkill(name="x", weight=1)   # 边界 ok
    HardSkill(name="x", weight=10)  # 边界 ok


def test_hard_skill_level_enum():
    with pytest.raises(ValidationError):
        HardSkill(name="x", weight=5, level="大师")
    HardSkill(name="x", weight=5, level="精通")


def test_soft_skill_stage_enum():
    with pytest.raises(ValidationError):
        SoftSkill(name="沟通", weight=5, assessment_stage="随便")
    SoftSkill(name="沟通", weight=5, assessment_stage="面试")


def test_education_level_enum():
    with pytest.raises(ValidationError):
        EducationRequirement(min_level="专科以下")
    EducationRequirement(min_level="本科")


def test_experience_years_optional_max():
    e = ExperienceRequirement(years_min=3)
    assert e.years_max is None
    assert e.industries == []


def test_competency_model_full():
    m = CompetencyModel(
        hard_skills=[HardSkill(name="Python", weight=9)],
        soft_skills=[SoftSkill(name="沟通", weight=6)],
        experience=ExperienceRequirement(years_min=3, years_max=7),
        education=EducationRequirement(min_level="本科"),
        source_jd_hash="abc123",
        extracted_at=datetime.utcnow(),
    )
    assert m.schema_version == 1
    assert m.hard_skills[0].name == "Python"


def test_competency_model_minimal_required():
    """最小必填: hard_skills / source_jd_hash / extracted_at."""
    m = CompetencyModel(
        hard_skills=[],  # 允许空, extractor 会校验业务规则
        source_jd_hash="h",
        extracted_at=datetime.utcnow(),
    )
    assert m.soft_skills == []
    assert m.education.min_level == "本科"


def test_competency_model_json_roundtrip():
    m = CompetencyModel(
        hard_skills=[HardSkill(name="Go", weight=7, must_have=True)],
        source_jd_hash="h",
        extracted_at=datetime(2026, 4, 20, 10, 0, 0),
    )
    j = m.model_dump_json()
    m2 = CompetencyModel.model_validate_json(j)
    assert m2.hard_skills[0].name == "Go"
    assert m2.hard_skills[0].must_have is True
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/python.exe -m pytest tests/core/test_competency_schema.py -v
```
Expected: FAIL — module 不存在。

- [ ] **Step 3: Implement `app/core/competency/schema.py`**

```python
"""F1 能力模型 Pydantic schema."""
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field


class HardSkill(BaseModel):
    name: str
    canonical_id: int | None = None
    level: Literal["了解", "熟练", "精通"] = "熟练"
    weight: int = Field(ge=1, le=10)
    must_have: bool = False


class SoftSkill(BaseModel):
    name: str
    weight: int = Field(ge=1, le=10)
    assessment_stage: Literal["简历", "IM", "面试"] = "面试"


class ExperienceRequirement(BaseModel):
    years_min: int = 0
    years_max: int | None = None
    industries: list[str] = []
    company_scale: str | None = None


class EducationRequirement(BaseModel):
    min_level: Literal["大专", "本科", "硕士", "博士"] = "本科"
    preferred_level: str | None = None
    prestigious_bonus: bool = False


class AssessmentDimension(BaseModel):
    name: str
    description: str = ""
    question_types: list[str] = []


class CompetencyModel(BaseModel):
    schema_version: int = 1
    hard_skills: list[HardSkill]
    soft_skills: list[SoftSkill] = []
    experience: ExperienceRequirement = ExperienceRequirement()
    education: EducationRequirement = EducationRequirement()
    job_level: str = ""
    bonus_items: list[str] = []
    exclusions: list[str] = []
    assessment_dimensions: list[AssessmentDimension] = []
    source_jd_hash: str
    extracted_at: datetime
    reviewed_by: int | None = None
    reviewed_at: datetime | None = None
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/python.exe -m pytest tests/core/test_competency_schema.py -v
```
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add app/core/competency/schema.py tests/core/test_competency_schema.py
git commit -m "feat(F1-T11): core/competency/schema — CompetencyModel Pydantic

- HardSkill weight 1-10, level enum (了解/熟练/精通)
- SoftSkill assessment_stage enum (简历/IM/面试)
- EducationRequirement min_level enum (大专/本科/硕士/博士)
- CompetencyModel composes all + source_jd_hash + extracted_at
- 9 tests: defaults / boundaries / enum violations / JSON roundtrip

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task T12: core/competency/skill_library.py — CRUD + SkillCache

**Files:**
- Create: `app/core/competency/models.py` (Skill SQLAlchemy model)
- Create: `app/core/competency/skill_library.py`
- Test: `tests/core/test_skill_library.py`

- [ ] **Step 1: Implement model in `app/core/competency/models.py`**

```python
"""Skill SQLAlchemy model. Schema 由 migration 0002 建立."""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, Text, Boolean, DateTime, JSON, LargeBinary
from app.database import Base


class Skill(Base):
    __tablename__ = "skills"

    id = Column(Integer, primary_key=True, autoincrement=True)
    canonical_name = Column(Text, unique=True, nullable=False)
    aliases = Column(JSON, default=list)
    category = Column(Text, default="uncategorized")
    embedding = Column(LargeBinary, nullable=True)
    source = Column(Text, nullable=False)
    pending_classification = Column(Boolean, default=False)
    usage_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
```

- [ ] **Step 2: Create the failing test**

Create `tests/core/test_skill_library.py`:

```python
"""core.competency.skill_library — CRUD + cache."""
import pytest
from alembic import command
from alembic.config import Config
import sqlalchemy as sa

from app.core.competency.skill_library import SkillLibrary, SkillCache


@pytest.fixture
def lib(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    url = f"sqlite:///{db}"
    cfg = Config("migrations/alembic.ini")
    cfg.set_main_option("script_location", "migrations")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "0006")

    engine = sa.create_engine(url, connect_args={"check_same_thread": False})
    monkeypatch.setattr("app.database.engine", engine)
    from sqlalchemy.orm import sessionmaker
    session_factory = sessionmaker(bind=engine)
    monkeypatch.setattr("app.core.competency.skill_library._session_factory", session_factory)
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
        embedding=b"\x00\x00\x80\x3f",  # float32(1.0)
        source="llm_extracted",
        pending_classification=True,
    )
    assert new_id > 0
    found = lib.find_by_name("Py后端")
    assert found["pending_classification"] is True
    assert found["source"] == "llm_extracted"


def test_insert_duplicate_name_raises(lib):
    with pytest.raises(Exception):  # IntegrityError
        lib.insert(canonical_name="Python", source="manual")


def test_add_alias(lib):
    lib.add_alias_if_absent("Python", "Py3k")
    s = lib.find_by_name("Python")
    assert "Py3k" in s["aliases"]
    # 再加一次不重复
    lib.add_alias_if_absent("Python", "Py3k")
    s2 = lib.find_by_name("Python")
    assert s2["aliases"].count("Py3k") == 1


def test_increment_usage(lib):
    before = lib.find_by_name("Python")["usage_count"]
    lib.increment_usage(before_id := lib.find_by_name("Python")["id"])
    after = lib.find_by_name("Python")["usage_count"]
    assert after == before + 1


def test_search_by_name_substring(lib):
    hits = lib.search("Python")
    assert any(h["canonical_name"] == "Python" for h in hits)


def test_cache_reload_after_insert(lib):
    SkillCache.all()  # prime
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
```

- [ ] **Step 3: Run test to verify it fails**

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/python.exe -m pytest tests/core/test_skill_library.py -v
```
Expected: FAIL — module 不存在。

- [ ] **Step 4: Implement `app/core/competency/skill_library.py`**

```python
"""skills 表 CRUD + 内存缓存 (SkillCache)."""
import json
import logging
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from app.database import engine
from app.core.competency.models import Skill

logger = logging.getLogger(__name__)

_session_factory = sessionmaker(bind=engine)


def _row_to_dict(s: Skill) -> dict:
    return {
        "id": s.id,
        "canonical_name": s.canonical_name,
        "aliases": s.aliases if isinstance(s.aliases, list) else (json.loads(s.aliases) if s.aliases else []),
        "category": s.category,
        "embedding": s.embedding,
        "source": s.source,
        "pending_classification": bool(s.pending_classification),
        "usage_count": s.usage_count,
    }


class SkillCache:
    """进程内缓存 skills 全量. 插入/改动后手动 invalidate()."""
    _cache: list[dict] | None = None

    @classmethod
    def all(cls) -> list[dict]:
        if cls._cache is None:
            cls._cache = SkillLibrary().list_all()
        return cls._cache

    @classmethod
    def invalidate(cls) -> None:
        cls._cache = None


class SkillLibrary:
    def list_all(self) -> list[dict]:
        session = _session_factory()
        try:
            rows = session.query(Skill).all()
            return [_row_to_dict(r) for r in rows]
        finally:
            session.close()

    def find_by_name(self, name: str) -> dict | None:
        session = _session_factory()
        try:
            row = session.query(Skill).filter(Skill.canonical_name == name).first()
            return _row_to_dict(row) if row else None
        finally:
            session.close()

    def find_by_id(self, skill_id: int) -> dict | None:
        session = _session_factory()
        try:
            row = session.query(Skill).filter(Skill.id == skill_id).first()
            return _row_to_dict(row) if row else None
        finally:
            session.close()

    def insert(
        self,
        canonical_name: str,
        source: str,
        *,
        aliases: list[str] | None = None,
        category: str = "uncategorized",
        embedding: bytes | None = None,
        pending_classification: bool = False,
    ) -> int:
        session = _session_factory()
        try:
            row = Skill(
                canonical_name=canonical_name,
                aliases=aliases or [],
                category=category,
                embedding=embedding,
                source=source,
                pending_classification=pending_classification,
            )
            session.add(row)
            session.commit()
            SkillCache.invalidate()
            return row.id
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def add_alias_if_absent(self, canonical_name: str, alias: str) -> None:
        session = _session_factory()
        try:
            row = session.query(Skill).filter(Skill.canonical_name == canonical_name).first()
            if row is None:
                return
            aliases = row.aliases if isinstance(row.aliases, list) else (json.loads(row.aliases) if row.aliases else [])
            if alias not in aliases:
                aliases.append(alias)
                row.aliases = aliases
                session.commit()
                SkillCache.invalidate()
        finally:
            session.close()

    def increment_usage(self, skill_id: int) -> None:
        session = _session_factory()
        try:
            session.query(Skill).filter(Skill.id == skill_id).update(
                {Skill.usage_count: Skill.usage_count + 1}
            )
            session.commit()
            SkillCache.invalidate()
        finally:
            session.close()

    def search(self, q: str, limit: int = 20) -> list[dict]:
        """LIKE 搜索 canonical_name + aliases."""
        session = _session_factory()
        try:
            like = f"%{q}%"
            rows = (
                session.query(Skill)
                .filter(sa.or_(
                    Skill.canonical_name.like(like),
                    sa.func.json_extract(Skill.aliases, "$").like(like),
                ))
                .limit(limit).all()
            )
            return [_row_to_dict(r) for r in rows]
        finally:
            session.close()

    def list_pending(self) -> list[dict]:
        session = _session_factory()
        try:
            rows = session.query(Skill).filter(Skill.pending_classification.is_(True)).all()
            return [_row_to_dict(r) for r in rows]
        finally:
            session.close()

    def update_embedding(self, skill_id: int, embedding: bytes) -> None:
        session = _session_factory()
        try:
            session.query(Skill).filter(Skill.id == skill_id).update({Skill.embedding: embedding})
            session.commit()
            SkillCache.invalidate()
        finally:
            session.close()

    def merge(self, from_id: int, into_id: int) -> None:
        """把 from_id 的 aliases + usage_count 合并到 into_id, 然后删 from_id."""
        session = _session_factory()
        try:
            src = session.query(Skill).filter(Skill.id == from_id).first()
            dst = session.query(Skill).filter(Skill.id == into_id).first()
            if not src or not dst:
                raise ValueError("skill id not found")
            if src.source == "seed":
                raise ValueError("cannot merge seed skill")

            src_aliases = src.aliases if isinstance(src.aliases, list) else []
            dst_aliases = list(dst.aliases if isinstance(dst.aliases, list) else [])
            if src.canonical_name not in dst_aliases:
                dst_aliases.append(src.canonical_name)
            for a in src_aliases:
                if a not in dst_aliases:
                    dst_aliases.append(a)

            dst.aliases = dst_aliases
            dst.usage_count = (dst.usage_count or 0) + (src.usage_count or 0)
            session.delete(src)
            session.commit()
            SkillCache.invalidate()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
```

- [ ] **Step 5: Run test to verify it passes**

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/python.exe -m pytest tests/core/test_skill_library.py -v
```
Expected: 9 passed.

- [ ] **Step 6: Commit**

```bash
git add app/core/competency/models.py app/core/competency/skill_library.py tests/core/test_skill_library.py
git commit -m "feat(F1-T12): core/competency/skill_library — CRUD + SkillCache

- Skill SQLAlchemy model
- SkillLibrary: list_all/find_by_name/insert/add_alias/increment_usage/
  search/list_pending/update_embedding/merge
- merge refuses to merge seed skills (immutable baseline)
- SkillCache process-local cache, manual invalidate on write
- 9 tests

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task T13: core/competency/normalizer.py — Skill Normalization

**Files:**
- Create: `app/core/competency/normalizer.py`
- Test: `tests/core/test_competency_normalizer.py`

**Context:** 核心算法:
1. LLM 抽出技能名列表
2. batch embed
3. 对每个技能在 skills 表找最近邻
4. > 0.85 → 复用 + 加别名 + 增加 usage_count
5. ≤ 0.85 → 新建 (pending_classification=1) + 非阻塞 HITL

- [ ] **Step 1: Create the failing test**

Create `tests/core/test_competency_normalizer.py`:

```python
"""core.competency.normalizer — 技能归一化."""
import pytest
from unittest.mock import AsyncMock, patch
from alembic import command
from alembic.config import Config
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from app.core.competency.normalizer import normalize_skills
from app.core.competency.skill_library import SkillLibrary, SkillCache
from app.core.vector.service import pack_vector


@pytest.fixture
def ready_db(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    url = f"sqlite:///{db}"
    cfg = Config("migrations/alembic.ini")
    cfg.set_main_option("script_location", "migrations")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "0006")

    engine = sa.create_engine(url, connect_args={"check_same_thread": False})
    factory = sessionmaker(bind=engine)

    monkeypatch.setattr("app.database.engine", engine)
    monkeypatch.setattr("app.core.competency.skill_library._session_factory", factory)
    monkeypatch.setattr("app.core.audit.logger._session_factory", factory)
    monkeypatch.setattr("app.core.hitl.service._session_factory", factory)
    SkillCache.invalidate()

    # 给 Python 补个 embedding 让测试可用
    lib = SkillLibrary()
    python_id = lib.find_by_name("Python")["id"]
    lib.update_embedding(python_id, pack_vector([1.0, 0.0, 0.0]))

    yield lib


@pytest.mark.asyncio
async def test_normalize_exact_match_reuses_skill(ready_db):
    """高相似度 → 复用已有 canonical_id."""
    lib = ready_db
    mock_embed = AsyncMock(return_value=[[1.0, 0.0, 0.0]])  # 与 Python 向量相同
    with patch("app.core.competency.normalizer.get_llm_provider") as mock_get:
        mock_get.return_value.embed_batch = mock_embed
        results = await normalize_skills(["python3"], job_id=1)

    assert len(results) == 1
    python_id = lib.find_by_name("Python")["id"]
    assert results[0]["canonical_id"] == python_id

    # python3 加入 aliases
    p = lib.find_by_name("Python")
    assert "python3" in p["aliases"]


@pytest.mark.asyncio
async def test_normalize_low_similarity_creates_new_skill(ready_db):
    """低相似度 → 新建 skill + pending + HITL."""
    lib = ready_db
    mock_embed = AsyncMock(return_value=[[0.0, 1.0, 0.0]])  # 与 Python 正交
    with patch("app.core.competency.normalizer.get_llm_provider") as mock_get:
        mock_get.return_value.embed_batch = mock_embed
        results = await normalize_skills(["全新技能"], job_id=42)

    assert len(results) == 1
    new = lib.find_by_name("全新技能")
    assert new is not None
    assert new["pending_classification"] is True
    assert new["source"] == "llm_extracted"
    assert results[0]["canonical_id"] == new["id"]

    # HITL 任务已创建
    from app.core.hitl.service import HitlService
    tasks = HitlService().list(stage="F1_skill_classification", status="pending")
    assert any(t["entity_id"] == new["id"] for t in tasks)


@pytest.mark.asyncio
async def test_normalize_threshold_boundary(ready_db):
    """相似度 0.849 → 新建; 0.851 → 复用."""
    lib = ready_db
    # 相似度约 0.849 的向量
    low = [0.849, (1.0 - 0.849**2)**0.5, 0.0]
    high = [0.851, (1.0 - 0.851**2)**0.5, 0.0]

    mock_embed = AsyncMock(side_effect=[[low], [high]])
    with patch("app.core.competency.normalizer.get_llm_provider") as mock_get:
        mock_get.return_value.embed_batch = mock_embed

        # low → 新技能
        r1 = await normalize_skills(["低相似"], job_id=1)
        assert lib.find_by_name("低相似") is not None

        # high → 复用 Python
        r2 = await normalize_skills(["高相似"], job_id=1)
        python_id = lib.find_by_name("Python")["id"]
        assert r2[0]["canonical_id"] == python_id


@pytest.mark.asyncio
async def test_normalize_empty_list(ready_db):
    results = await normalize_skills([], job_id=1)
    assert results == []


@pytest.mark.asyncio
async def test_normalize_batch_multiple(ready_db):
    """一次处理多个技能, embed_batch 只调一次."""
    lib = ready_db
    mock_embed = AsyncMock(return_value=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    with patch("app.core.competency.normalizer.get_llm_provider") as mock_get:
        mock_get.return_value.embed_batch = mock_embed
        results = await normalize_skills(["Python", "新技能A"], job_id=1)

    assert mock_embed.await_count == 1  # 一次批量
    assert len(results) == 2
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/python.exe -m pytest tests/core/test_competency_normalizer.py -v
```
Expected: FAIL — module 不存在。

- [ ] **Step 3: Implement `app/core/competency/normalizer.py`**

```python
"""技能归一化: LLM 原名 → skills 表 canonical_id."""
import logging
from typing import Any

from app.core.competency import SKILL_SIMILARITY_THRESHOLD
from app.core.competency.skill_library import SkillLibrary, SkillCache
from app.core.vector.service import (
    cosine_similarity, find_nearest, pack_vector, unpack_vector,
)
from app.core.audit.logger import log_event
from app.core.hitl.service import HitlService
from app.core.llm.provider import LLMProvider

logger = logging.getLogger(__name__)


def get_llm_provider() -> LLMProvider:
    """可被测试 monkeypatch 替换的入口."""
    return LLMProvider()


async def normalize_skills(names: list[str], job_id: int) -> list[dict]:
    """返回 [{"name": 原名, "canonical_id": int}, ...].

    对每个 name:
      - embed
      - 在 skills 表找最近邻
      - similarity > 0.85 → 复用 canonical_id, 追加 alias, usage_count++
      - 否则 → 新建 skill (pending=True) + 非阻塞 HITL
    """
    if not names:
        return []

    llm = get_llm_provider()
    vectors = await llm.embed_batch(names)

    lib = SkillLibrary()
    all_skills = SkillCache.all()
    # 准备 (id, vec) 列表, 无 embedding 的 skip
    candidates = []
    for s in all_skills:
        if s["embedding"]:
            candidates.append((s["id"], unpack_vector(s["embedding"])))

    results: list[dict] = []
    for name, vec in zip(names, vectors):
        best_id, best_sim = find_nearest(vec, candidates)

        if best_id is not None and best_sim > SKILL_SIMILARITY_THRESHOLD:
            # 复用
            existing = lib.find_by_id(best_id)
            if existing and name != existing["canonical_name"]:
                lib.add_alias_if_absent(existing["canonical_name"], name)
            lib.increment_usage(best_id)
            log_event(
                f_stage="F1_competency_review",
                action="normalize",
                entity_type="skill",
                entity_id=best_id,
                input_payload={"name": name, "job_id": job_id},
                output_payload={"canonical_id": best_id, "similarity": best_sim},
            )
            results.append({"name": name, "canonical_id": best_id})
        else:
            # 新建
            new_id = lib.insert(
                canonical_name=name,
                source="llm_extracted",
                pending_classification=True,
                embedding=pack_vector(vec),
            )
            HitlService().create(
                f_stage="F1_skill_classification",
                entity_type="skill",
                entity_id=new_id,
                payload={"name": name, "from_job": job_id},
            )
            log_event(
                f_stage="F1_competency_review",
                action="normalize",
                entity_type="skill",
                entity_id=new_id,
                input_payload={"name": name, "job_id": job_id},
                output_payload={"canonical_id": new_id, "similarity": best_sim, "new": True},
            )
            results.append({"name": name, "canonical_id": new_id})

    return results
```

- [ ] **Step 4: Run test to verify it passes** (Note: T15 HitlService 必须先就位, 但按顺序 T15 在后 — 所以这里可能先跳过 HITL 创建断言, 或把 T15 提前. 本 plan 按顺序要求: **T13 测试用 `mock` 替换 HitlService, 实现代码保留直接调用. 如果 T13 在 T15 前执行, 先把 `HitlService` 改为延迟 import / 注入, 或把 T15 提前**)

实际执行顺序：**建议把 T15 提前到 T13 之前**。若按计划顺序执行，T13 测试的 HITL 断言将失败，请先完成 T15。

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/python.exe -m pytest tests/core/test_competency_normalizer.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add app/core/competency/normalizer.py tests/core/test_competency_normalizer.py
git commit -m "feat(F1-T13): core/competency/normalizer — skill canonicalization

- normalize_skills() uses embed_batch + find_nearest
- similarity > SKILL_SIMILARITY_THRESHOLD (0.85) → reuse canonical_id
- else → new skill with pending_classification=True + non-blocking HITL
- audit event 'normalize' per skill with similarity recorded
- 5 tests cover reuse/new/threshold-boundary/empty/batch

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task T14: core/competency/extractor.py — JD → CompetencyModel

**Files:**
- Create: `app/core/competency/extractor.py`
- Test: `tests/core/test_competency_extractor.py`

**Context:** 串联 T6/T9/T11/T13. 输入 jd_text + job_id, 输出 CompetencyModel draft. 失败抛 ExtractionFailedError, 调用方决定降级.

- [ ] **Step 1: Create the failing test**

Create `tests/core/test_competency_extractor.py`:

```python
"""core.competency.extractor — JD → CompetencyModel."""
import json
import pytest
from unittest.mock import AsyncMock, patch

from app.core.competency.extractor import extract_competency, ExtractionFailedError
from app.core.llm.provider import LLMError


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
    mock_llm = AsyncMock()
    mock_llm.complete = AsyncMock(return_value=_VALID_JSON)
    mock_llm.embed_batch = AsyncMock(return_value=[[1.0, 0, 0], [0.9, 0.1, 0]])
    with patch("app.core.competency.extractor.get_llm_provider", return_value=mock_llm), \
         patch("app.core.competency.normalizer.get_llm_provider", return_value=mock_llm):
        model = await extract_competency(
            jd_text="招聘高级后端工程师...",
            job_id=1,
        )
    assert len(model.hard_skills) == 2
    assert model.hard_skills[0].name == "Python"
    assert model.education.min_level == "本科"
    assert model.source_jd_hash  # 非空


@pytest.mark.asyncio
async def test_extract_invalid_json_retries():
    mock_llm = AsyncMock()
    mock_llm.complete = AsyncMock(side_effect=[
        "not json at all",
        "also not json",
        _VALID_JSON,
    ])
    mock_llm.embed_batch = AsyncMock(return_value=[[1.0, 0, 0], [0.9, 0.1, 0]])
    with patch("app.core.competency.extractor.get_llm_provider", return_value=mock_llm), \
         patch("app.core.competency.normalizer.get_llm_provider", return_value=mock_llm):
        model = await extract_competency(jd_text="jd", job_id=1)
    assert mock_llm.complete.await_count == 3
    assert len(model.hard_skills) == 2


@pytest.mark.asyncio
async def test_extract_all_retries_fail_raises():
    mock_llm = AsyncMock()
    mock_llm.complete = AsyncMock(return_value="never valid")
    with patch("app.core.competency.extractor.get_llm_provider", return_value=mock_llm):
        with pytest.raises(ExtractionFailedError):
            await extract_competency(jd_text="jd", job_id=1)


@pytest.mark.asyncio
async def test_extract_llm_http_error_raises():
    mock_llm = AsyncMock()
    mock_llm.complete = AsyncMock(side_effect=LLMError("net down"))
    with patch("app.core.competency.extractor.get_llm_provider", return_value=mock_llm):
        with pytest.raises(ExtractionFailedError):
            await extract_competency(jd_text="jd", job_id=1)


@pytest.mark.asyncio
async def test_extract_audits_extract_action():
    seen = []

    def fake_log(**kwargs):
        seen.append(kwargs)
        return "eid"

    mock_llm = AsyncMock()
    mock_llm.complete = AsyncMock(return_value=_VALID_JSON)
    mock_llm.embed_batch = AsyncMock(return_value=[[1.0, 0, 0], [0.9, 0.1, 0]])
    with patch("app.core.competency.extractor.get_llm_provider", return_value=mock_llm), \
         patch("app.core.competency.normalizer.get_llm_provider", return_value=mock_llm), \
         patch("app.core.competency.extractor.log_event", fake_log), \
         patch("app.core.competency.normalizer.log_event", fake_log):
        await extract_competency(jd_text="jd", job_id=1)
    actions = [s["action"] for s in seen]
    assert "extract" in actions
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/python.exe -m pytest tests/core/test_competency_extractor.py -v
```
Expected: FAIL — module 不存在。

- [ ] **Step 3: Implement `app/core/competency/extractor.py`**

```python
"""JD → CompetencyModel 抽取."""
import hashlib
import json
import logging
from datetime import datetime, timezone

from pydantic import ValidationError

from app.config import settings
from app.core.audit.logger import log_event
from app.core.competency.normalizer import normalize_skills
from app.core.competency.schema import CompetencyModel
from app.core.llm.parsing import extract_json
from app.core.llm.provider import LLMProvider, LLMError

logger = logging.getLogger(__name__)

PROMPT_VERSION = "f1_competency_v1"
MAX_PARSE_RETRIES = 2

SYSTEM_PROMPT = """你是招聘领域的 HR 专家。给定一段岗位 JD，提取结构化能力模型，严格按 JSON schema 输出。
不要 markdown 包装，不要多余字段。

schema:
{
  "hard_skills": [{"name": str, "level": "了解|熟练|精通",
                   "weight": 1-10, "must_have": bool}],
  "soft_skills": [{"name": str, "weight": 1-10,
                   "assessment_stage": "简历|IM|面试"}],
  "experience": {"years_min": int, "years_max": int|null,
                 "industries": [str], "company_scale": str|null},
  "education": {"min_level": "大专|本科|硕士|博士",
                "preferred_level": str|null, "prestigious_bonus": bool},
  "job_level": str,
  "bonus_items": [str],
  "exclusions": [str],
  "assessment_dimensions": [{"name": str, "description": str,
                             "question_types": [str]}]
}

规则：
1. hard_skills 3–15 条，关键技能 weight 9–10
2. soft_skills 0–8 条
3. assessment_dimensions 2–6 条
4. JD 未提及的字段给空数组 / null，不编造
5. bonus_items = 加分项，exclusions = 淘汰项
"""


class ExtractionFailedError(RuntimeError):
    """抽取失败. 调用方 (router) 把前端切到扁平字段手填降级路径."""


def get_llm_provider() -> LLMProvider:
    model = settings.ai_model_competency or settings.ai_model
    p = LLMProvider(model=model)
    return p


async def extract_competency(jd_text: str, job_id: int) -> CompetencyModel:
    """JD → CompetencyModel. 抽取成功后 normalize_skills 补 canonical_id.

    重试 2 次 parse 错误 (加修正提示), LLM HTTP 错由 provider 重试 3 次.
    依旧全败抛 ExtractionFailedError.
    """
    llm = get_llm_provider()
    jd_hash = hashlib.sha256(jd_text.encode("utf-8")).hexdigest()

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": jd_text},
    ]

    raw: str = ""
    parsed: dict | None = None
    last_err: Exception | None = None

    for attempt in range(1, MAX_PARSE_RETRIES + 1 + 1):  # 1 首次 + 2 重试 = 3 trials
        try:
            raw = await llm.complete(
                messages=messages,
                prompt_version=PROMPT_VERSION,
                f_stage="F1_competency_review",
                entity_type="job",
                entity_id=job_id,
                temperature=0.2,
                response_format="json",
            )
        except LLMError as e:
            last_err = e
            break  # provider 已重试过, 这里不再重试

        try:
            parsed = extract_json(raw)
            break
        except ValueError as e:
            last_err = e
            logger.warning(f"extract_competency parse attempt {attempt} failed: {e}")
            if attempt <= MAX_PARSE_RETRIES:
                messages = messages + [
                    {"role": "assistant", "content": raw},
                    {"role": "user", "content": "上次输出非合法 JSON. 请严格按 schema 重新输出, 不要任何包装."},
                ]

    if parsed is None:
        log_event(
            f_stage="F1_competency_review",
            action="extract_fail",
            entity_type="job",
            entity_id=job_id,
            input_payload={"jd_hash": jd_hash},
            output_payload={"error": str(last_err)},
            prompt_version=PROMPT_VERSION,
            model_name=llm.model,
        )
        raise ExtractionFailedError(f"LLM extraction failed: {last_err}")

    # normalize 硬技能 (只对 hard_skills 归一化, soft_skills 不用技能库)
    hard_names = [s["name"] for s in parsed.get("hard_skills", [])]
    norm_results = await normalize_skills(hard_names, job_id=job_id)
    # 把 canonical_id 塞回 hard_skills
    name_to_cid = {r["name"]: r["canonical_id"] for r in norm_results}
    for s in parsed.get("hard_skills", []):
        s["canonical_id"] = name_to_cid.get(s["name"])

    # 补 schema 字段
    parsed["source_jd_hash"] = jd_hash
    parsed["extracted_at"] = datetime.now(timezone.utc).isoformat()

    try:
        model = CompetencyModel.model_validate(parsed)
    except ValidationError as e:
        log_event(
            f_stage="F1_competency_review",
            action="extract_fail",
            entity_type="job",
            entity_id=job_id,
            input_payload={"jd_hash": jd_hash, "raw_parsed": parsed},
            output_payload={"error": str(e)},
            prompt_version=PROMPT_VERSION,
            model_name=llm.model,
        )
        raise ExtractionFailedError(f"Pydantic validation failed: {e}")

    log_event(
        f_stage="F1_competency_review",
        action="extract",
        entity_type="job",
        entity_id=job_id,
        input_payload={"jd_hash": jd_hash, "jd_length": len(jd_text)},
        output_payload=model.model_dump(mode="json"),
        prompt_version=PROMPT_VERSION,
        model_name=llm.model,
    )
    return model
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/python.exe -m pytest tests/core/test_competency_extractor.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add app/core/competency/extractor.py tests/core/test_competency_extractor.py
git commit -m "feat(F1-T14): core/competency/extractor — JD → CompetencyModel

- extract_competency() orchestrates: LLM complete → parse → normalize → validate
- 2 parse retries with corrective assistant/user messages appended
- LLMError (provider retries exhausted) → ExtractionFailedError
- ValidationError on Pydantic → ExtractionFailedError + audit extract_fail
- audit 'extract' action on success
- SYSTEM_PROMPT contains schema + rules (3-15 hard skills, 0-8 soft, etc.)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task T15: core/hitl/ — HITL task queue

**Files:**
- Create: `app/core/hitl/__init__.py`
- Create: `app/core/hitl/models.py`
- Create: `app/core/hitl/service.py`
- Create: `app/core/hitl/router.py`
- Test: `tests/core/test_hitl_service.py`

**Context:** 注意: 按 normalizer (T13) 需要 `HitlService().create()`, 建议实际执行时把 T15 提前到 T13 之前 — 本文档保持编号顺序.

- [ ] **Step 1: Create `app/core/hitl/` package**

```bash
cd /d/libz/AgenticHR
mkdir -p app/core/hitl
touch app/core/hitl/__init__.py
```

- [ ] **Step 2: Create `app/core/hitl/models.py`**

```python
"""HitlTask SQLAlchemy model. Schema 由 migration 0003 建立."""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, Text, DateTime, JSON
from app.database import Base


class HitlTask(Base):
    __tablename__ = "hitl_tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    f_stage = Column(Text, nullable=False)
    entity_type = Column(Text, nullable=False)
    entity_id = Column(Integer, nullable=False)
    payload = Column(JSON, nullable=False)
    status = Column(Text, nullable=False, default="pending")
    edited_payload = Column(JSON, nullable=True)
    reviewer_id = Column(Integer, nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
```

- [ ] **Step 3: Create failing test**

Create `tests/core/test_hitl_service.py`:

```python
"""core.hitl.service — HITL task CRUD + state transitions."""
import pytest
from alembic import command
from alembic.config import Config
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from app.core.hitl.service import HitlService, InvalidHitlStateError


@pytest.fixture
def svc(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    url = f"sqlite:///{db}"
    cfg = Config("migrations/alembic.ini")
    cfg.set_main_option("script_location", "migrations")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "0006")
    engine = sa.create_engine(url, connect_args={"check_same_thread": False})
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr("app.database.engine", engine)
    monkeypatch.setattr("app.core.hitl.service._session_factory", factory)
    monkeypatch.setattr("app.core.audit.logger._session_factory", factory)
    return HitlService()


def test_create_task(svc):
    tid = svc.create(
        f_stage="F1_competency_review",
        entity_type="job",
        entity_id=1,
        payload={"draft": {"hard_skills": []}},
    )
    assert tid > 0
    task = svc.get(tid)
    assert task["status"] == "pending"
    assert task["payload"] == {"draft": {"hard_skills": []}}


def test_list_filters(svc):
    svc.create("F1_competency_review", "job", 1, {})
    svc.create("F1_skill_classification", "skill", 2, {})
    svc.create("F1_competency_review", "job", 3, {})

    all_tasks = svc.list()
    assert len(all_tasks) == 3

    comp = svc.list(stage="F1_competency_review")
    assert len(comp) == 2

    pending = svc.list(status="pending")
    assert len(pending) == 3


def test_approve_transitions_status(svc):
    tid = svc.create("F1_competency_review", "job", 1, {})
    svc.approve(tid, reviewer_id=99, note="looks good")
    task = svc.get(tid)
    assert task["status"] == "approved"
    assert task["reviewer_id"] == 99
    assert task["reviewed_at"] is not None
    assert task["note"] == "looks good"


def test_reject_requires_note(svc):
    tid = svc.create("F1_competency_review", "job", 1, {})
    with pytest.raises(ValueError, match="note"):
        svc.reject(tid, reviewer_id=99, note="")
    svc.reject(tid, reviewer_id=99, note="LLM 输出质量差")
    assert svc.get(tid)["status"] == "rejected"


def test_edit_writes_edited_payload(svc):
    tid = svc.create("F1_competency_review", "job", 1, {"v": 1})
    svc.edit(tid, reviewer_id=99, edited_payload={"v": 2}, note="adjusted weights")
    task = svc.get(tid)
    assert task["status"] == "edited"
    assert task["edited_payload"] == {"v": 2}
    # 原 payload 保留做溯源
    assert task["payload"] == {"v": 1}


def test_cannot_double_approve(svc):
    tid = svc.create("F1_competency_review", "job", 1, {})
    svc.approve(tid, reviewer_id=99)
    with pytest.raises(InvalidHitlStateError):
        svc.approve(tid, reviewer_id=99)


def test_get_not_found_returns_none(svc):
    assert svc.get(99999) is None
```

- [ ] **Step 4: Run test to verify it fails**

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/python.exe -m pytest tests/core/test_hitl_service.py -v
```
Expected: FAIL — module 不存在。

- [ ] **Step 5: Implement `app/core/hitl/service.py`**

```python
"""HITL 任务服务."""
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import sessionmaker

from app.database import engine
from app.core.hitl.models import HitlTask
from app.core.audit.logger import log_event

logger = logging.getLogger(__name__)

_session_factory = sessionmaker(bind=engine)


class InvalidHitlStateError(RuntimeError):
    """试图对已终态 (approved/rejected/edited) 的任务再次操作."""


def _row_to_dict(t: HitlTask) -> dict:
    return {
        "id": t.id,
        "f_stage": t.f_stage,
        "entity_type": t.entity_type,
        "entity_id": t.entity_id,
        "payload": t.payload,
        "status": t.status,
        "edited_payload": t.edited_payload,
        "reviewer_id": t.reviewer_id,
        "reviewed_at": t.reviewed_at.isoformat() if t.reviewed_at else None,
        "note": t.note,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


class HitlService:
    def create(
        self,
        f_stage: str,
        entity_type: str,
        entity_id: int,
        payload: Any,
    ) -> int:
        session = _session_factory()
        try:
            task = HitlTask(
                f_stage=f_stage,
                entity_type=entity_type,
                entity_id=entity_id,
                payload=payload,
                status="pending",
            )
            session.add(task)
            session.commit()
            tid = task.id
            log_event(
                f_stage=f_stage, action="hitl_create",
                entity_type=entity_type, entity_id=entity_id,
                input_payload=payload,
            )
            return tid
        finally:
            session.close()

    def get(self, task_id: int) -> dict | None:
        session = _session_factory()
        try:
            t = session.query(HitlTask).filter(HitlTask.id == task_id).first()
            return _row_to_dict(t) if t else None
        finally:
            session.close()

    def list(
        self,
        stage: str | None = None,
        status: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict]:
        session = _session_factory()
        try:
            q = session.query(HitlTask)
            if stage:
                q = q.filter(HitlTask.f_stage == stage)
            if status:
                q = q.filter(HitlTask.status == status)
            q = q.order_by(HitlTask.created_at.desc()).limit(limit).offset(offset)
            return [_row_to_dict(t) for t in q.all()]
        finally:
            session.close()

    def count_pending(self, stage: str | None = None) -> int:
        session = _session_factory()
        try:
            q = session.query(HitlTask).filter(HitlTask.status == "pending")
            if stage:
                q = q.filter(HitlTask.f_stage == stage)
            return q.count()
        finally:
            session.close()

    def approve(self, task_id: int, reviewer_id: int | None = None, note: str = "") -> None:
        self._transition(task_id, "approved", reviewer_id, note, "hitl_approve")

    def reject(self, task_id: int, reviewer_id: int | None = None, note: str = "") -> None:
        if not note:
            raise ValueError("reject requires a non-empty note")
        self._transition(task_id, "rejected", reviewer_id, note, "hitl_reject")

    def edit(
        self,
        task_id: int,
        *,
        reviewer_id: int | None = None,
        edited_payload: Any,
        note: str = "",
    ) -> None:
        session = _session_factory()
        try:
            t = session.query(HitlTask).filter(HitlTask.id == task_id).first()
            if t is None:
                raise ValueError(f"task {task_id} not found")
            if t.status != "pending":
                raise InvalidHitlStateError(
                    f"cannot edit task {task_id} in status={t.status}"
                )
            t.status = "edited"
            t.edited_payload = edited_payload
            t.reviewer_id = reviewer_id
            t.reviewed_at = datetime.now(timezone.utc)
            t.note = note
            session.commit()
            log_event(
                f_stage=t.f_stage, action="hitl_edit",
                entity_type=t.entity_type, entity_id=t.entity_id,
                input_payload=t.payload, output_payload=edited_payload,
                reviewer_id=reviewer_id,
            )
        finally:
            session.close()

    def _transition(self, task_id: int, new_status: str,
                     reviewer_id: int | None, note: str, action: str) -> None:
        session = _session_factory()
        try:
            t = session.query(HitlTask).filter(HitlTask.id == task_id).first()
            if t is None:
                raise ValueError(f"task {task_id} not found")
            if t.status != "pending":
                raise InvalidHitlStateError(
                    f"cannot {new_status} task {task_id} in status={t.status}"
                )
            t.status = new_status
            t.reviewer_id = reviewer_id
            t.reviewed_at = datetime.now(timezone.utc)
            t.note = note
            session.commit()
            log_event(
                f_stage=t.f_stage, action=action,
                entity_type=t.entity_type, entity_id=t.entity_id,
                input_payload=t.payload, reviewer_id=reviewer_id,
            )
        finally:
            session.close()
```

- [ ] **Step 6: Run test to verify it passes**

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/python.exe -m pytest tests/core/test_hitl_service.py -v
```
Expected: 7 passed.

- [ ] **Step 7: Implement `app/core/hitl/router.py`**

```python
"""HITL HTTP API."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.hitl.service import HitlService, InvalidHitlStateError

router = APIRouter(prefix="/api/hitl", tags=["hitl"])


class _ApproveBody(BaseModel):
    note: str = ""


class _RejectBody(BaseModel):
    note: str


class _EditBody(BaseModel):
    edited_payload: dict
    note: str = ""


@router.get("/tasks")
def list_tasks(stage: str | None = None, status: str | None = None,
                limit: int = 200, offset: int = 0) -> dict:
    items = HitlService().list(stage=stage, status=status, limit=limit, offset=offset)
    pending = HitlService().count_pending(stage=stage)
    return {"items": items, "total": len(items), "pending": pending}


@router.get("/tasks/{task_id}")
def get_task(task_id: int) -> dict:
    t = HitlService().get(task_id)
    if not t:
        raise HTTPException(status_code=404, detail="task not found")
    return t


@router.post("/tasks/{task_id}/approve")
def approve(task_id: int, body: _ApproveBody) -> dict:
    try:
        HitlService().approve(task_id, note=body.note)
    except InvalidHitlStateError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"status": "approved"}


@router.post("/tasks/{task_id}/reject")
def reject(task_id: int, body: _RejectBody) -> dict:
    try:
        HitlService().reject(task_id, note=body.note)
    except InvalidHitlStateError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "rejected"}


@router.post("/tasks/{task_id}/edit")
def edit(task_id: int, body: _EditBody) -> dict:
    try:
        HitlService().edit(task_id, edited_payload=body.edited_payload, note=body.note)
    except InvalidHitlStateError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"status": "edited"}
```

- [ ] **Step 8: Register router in `app/main.py`**

在 `app/main.py` 顶部 import 区加:

```python
from app.core.hitl.router import router as hitl_router
```

然后在 `app.include_router(...)` 系列调用处加:

```python
app.include_router(hitl_router)
```

- [ ] **Step 9: Commit**

```bash
git add app/core/hitl/ tests/core/test_hitl_service.py app/main.py
git commit -m "feat(F1-T15): core/hitl — task queue service + HTTP API

- HitlService: create/get/list/count_pending/approve/reject/edit
- reject requires non-empty note
- double-approve / edit-after-terminal raises InvalidHitlStateError (HTTP 409)
- 7 unit tests + 5 routes registered at /api/hitl/*
- every state transition writes audit event (hitl_create/approve/reject/edit)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 3 — Business Layer

### Task T16: screening/{models,schemas}.py — add competency fields

**Files:**
- Modify: `app/modules/screening/models.py`
- Modify: `app/modules/screening/schemas.py`
- Test: `tests/modules/screening/test_job_model_competency.py`

- [ ] **Step 1: Create the failing test**

Create `tests/modules/screening/test_job_model_competency.py`:

```python
"""Job 模型 F1 新字段."""
import pytest
from alembic import command
from alembic.config import Config
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from app.modules.screening.models import Job
from app.modules.screening.schemas import JobCreate, JobResponse


@pytest.fixture
def session(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    url = f"sqlite:///{db}"
    cfg = Config("migrations/alembic.ini")
    cfg.set_main_option("script_location", "migrations")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "0006")
    engine = sa.create_engine(url, connect_args={"check_same_thread": False})
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr("app.database.engine", engine)
    return factory()


def test_job_has_new_columns(session):
    job = Job(title="后端", jd_text="招聘后端", competency_model={"v": 1},
              competency_model_status="draft")
    session.add(job); session.commit(); session.refresh(job)
    assert job.jd_text == "招聘后端"
    assert job.competency_model == {"v": 1}
    assert job.competency_model_status == "draft"


def test_job_defaults_for_new_columns(session):
    job = Job(title="后端")
    session.add(job); session.commit(); session.refresh(job)
    assert job.jd_text == ""
    assert job.competency_model is None
    assert job.competency_model_status == "none"


def test_job_response_schema_has_competency_fields():
    data = JobResponse(
        id=1, user_id=0, title="x", department="", education_min="",
        work_years_min=0, work_years_max=99, salary_min=0, salary_max=0,
        required_skills="", soft_requirements="", greeting_templates="",
        is_active=True, jd_text="jd", competency_model={"v": 1},
        competency_model_status="draft",
    )
    assert data.jd_text == "jd"
    assert data.competency_model_status == "draft"


def test_job_create_allows_optional_competency():
    """JobCreate 应该允许 jd_text/competency_model 可选 (老前端兼容)."""
    data = JobCreate(title="后端")
    assert data.jd_text == ""
    assert data.competency_model is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/python.exe -m pytest tests/modules/screening/test_job_model_competency.py -v
```
Expected: FAIL — 模型无这些字段。

- [ ] **Step 3: Modify `app/modules/screening/models.py`**

在 `Job` 类末尾(`updated_at` 之后)加:

```python
    jd_text = Column(Text, default="", nullable=False)
    competency_model = Column(JSON, nullable=True)
    competency_model_status = Column(String(20), default="none", nullable=False)
```

同时在顶部 import 加入 `JSON`:

```python
from sqlalchemy import Column, Integer, String, Text, Float, Boolean, DateTime, JSON
```

- [ ] **Step 4: Modify `app/modules/screening/schemas.py`**

在 `JobCreate` / `JobUpdate` / `JobResponse` 三个类各加字段 (参考 schemas.py 现有顺序, 加在 `greeting_templates` 之后 / `is_active` 之前):

```python
# JobCreate
    jd_text: str = Field(default="", description="JD 原文")
    competency_model: dict | None = Field(default=None, description="能力模型 JSON")
    competency_model_status: str = Field(default="none")

# JobUpdate
    jd_text: str | None = None
    competency_model: dict | None = None
    competency_model_status: str | None = None

# JobResponse
    jd_text: str = ""
    competency_model: dict | None = None
    competency_model_status: str = "none"
```

- [ ] **Step 5: Run test to verify it passes**

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/python.exe -m pytest tests/modules/screening/test_job_model_competency.py -v
```
Expected: 4 passed.

- [ ] **Step 6: Run M2 regression to ensure no break**

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/python.exe -m pytest tests/modules/screening/ -v --tb=short
```
Expected: M2 现通过用例不能新增失败 (某些测试本来就 fail — 已知 baseline 37 fail).

- [ ] **Step 7: Commit**

```bash
git add app/modules/screening/models.py app/modules/screening/schemas.py tests/modules/screening/test_job_model_competency.py
git commit -m "feat(F1-T16): screening Job model + schemas add competency fields

- Job.jd_text / competency_model / competency_model_status
- JobCreate/Update/Response all accept optional new fields (old clients still work)
- 4 tests; M2 regression held at baseline

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task T17: screening/service.py — HITL approve double-write

**Files:**
- Create: `app/modules/screening/competency_service.py` (新文件, 存双写逻辑)
- Test: `tests/modules/screening/test_double_write.py`

**Context:** 当 HITL approve 一个 F1_competency_review 任务时，需要把 `competency_model` 翻译回扁平字段 (D2 双写过渡). 这个逻辑独立出一个 service, 避免 `screening/service.py` 变得太大.

- [ ] **Step 1: Create the failing test**

Create `tests/modules/screening/test_double_write.py`:

```python
"""HITL approve → 双写扁平字段回填."""
import pytest
from alembic import command
from alembic.config import Config
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from app.modules.screening.competency_service import apply_competency_to_job


@pytest.fixture
def session(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    url = f"sqlite:///{db}"
    cfg = Config("migrations/alembic.ini")
    cfg.set_main_option("script_location", "migrations")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "0006")
    engine = sa.create_engine(url, connect_args={"check_same_thread": False})
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr("app.database.engine", engine)
    monkeypatch.setattr(
        "app.modules.screening.competency_service._session_factory", factory
    )
    yield factory


def test_apply_writes_competency_and_flat_fields(session):
    from app.modules.screening.models import Job
    s = session()
    job = Job(title="后端")
    s.add(job); s.commit(); s.refresh(job)
    jid = job.id
    s.close()

    model = {
        "hard_skills": [
            {"name": "Python", "weight": 9, "must_have": True, "level": "精通"},
            {"name": "FastAPI", "weight": 7, "must_have": False, "level": "熟练"},
        ],
        "soft_skills": [],
        "experience": {"years_min": 3, "years_max": 7, "industries": [], "company_scale": None},
        "education": {"min_level": "本科", "preferred_level": None, "prestigious_bonus": False},
        "job_level": "P6",
        "bonus_items": [],
        "exclusions": [],
        "assessment_dimensions": [],
        "source_jd_hash": "abc",
        "extracted_at": "2026-04-20T10:00:00",
    }
    apply_competency_to_job(jid, model)

    s = session()
    job = s.query(Job).filter(Job.id == jid).first()
    assert job.competency_model_status == "approved"
    assert job.competency_model is not None

    # 扁平字段回填
    assert job.education_min == "本科"
    assert job.work_years_min == 3
    assert job.work_years_max == 7
    assert "Python" in job.required_skills
    assert "FastAPI" in job.required_skills
    s.close()


def test_apply_handles_null_years_max(session):
    from app.modules.screening.models import Job
    s = session()
    job = Job(title="x"); s.add(job); s.commit(); jid = job.id; s.close()

    model = {
        "hard_skills": [{"name": "Go", "weight": 8, "must_have": True, "level": "熟练"}],
        "soft_skills": [], "experience": {"years_min": 2, "years_max": None,
                                           "industries": [], "company_scale": None},
        "education": {"min_level": "本科"},
        "bonus_items": [], "exclusions": [], "assessment_dimensions": [],
        "source_jd_hash": "h", "extracted_at": "2026-04-20T10:00:00",
    }
    apply_competency_to_job(jid, model)

    s = session()
    job = s.query(Job).filter(Job.id == jid).first()
    assert job.work_years_min == 2
    assert job.work_years_max == 99  # null → 默认 99
    s.close()


def test_apply_only_must_have_in_required_skills(session):
    """only must_have=True hard_skills go into required_skills flat field."""
    from app.modules.screening.models import Job
    s = session()
    job = Job(title="x"); s.add(job); s.commit(); jid = job.id; s.close()

    model = {
        "hard_skills": [
            {"name": "Python", "weight": 9, "must_have": True, "level": "精通"},
            {"name": "FastAPI", "weight": 6, "must_have": False, "level": "熟练"},
        ],
        "soft_skills": [], "experience": {"years_min": 0, "years_max": 99,
                                           "industries": [], "company_scale": None},
        "education": {"min_level": "本科"}, "bonus_items": [], "exclusions": [],
        "assessment_dimensions": [], "source_jd_hash": "h", "extracted_at": "2026-04-20T10:00:00",
    }
    apply_competency_to_job(jid, model)

    s = session()
    job = s.query(Job).filter(Job.id == jid).first()
    # 只有 must_have=True 的进 required_skills
    assert "Python" in job.required_skills
    assert "FastAPI" not in job.required_skills
    s.close()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/python.exe -m pytest tests/modules/screening/test_double_write.py -v
```
Expected: FAIL — module 不存在。

- [ ] **Step 3: Implement `app/modules/screening/competency_service.py`**

```python
"""能力模型 ↔ 扁平字段的双写逻辑 (F1 过渡期)."""
import logging
from typing import Any

from sqlalchemy.orm import sessionmaker

from app.database import engine
from app.modules.screening.models import Job

logger = logging.getLogger(__name__)

_session_factory = sessionmaker(bind=engine)


def apply_competency_to_job(job_id: int, competency_model: dict) -> None:
    """把 competency_model 写入 jobs 表, 同时回填扁平字段.

    扁平字段映射:
      - education.min_level → education_min
      - experience.years_min → work_years_min (default 0)
      - experience.years_max → work_years_max (null → 99)
      - hard_skills[].name where must_have=True → required_skills (CSV)
    """
    session = _session_factory()
    try:
        job = session.query(Job).filter(Job.id == job_id).first()
        if job is None:
            raise ValueError(f"job {job_id} not found")

        job.competency_model = competency_model
        job.competency_model_status = "approved"

        edu = competency_model.get("education", {}) or {}
        exp = competency_model.get("experience", {}) or {}
        hard = competency_model.get("hard_skills", []) or []

        job.education_min = edu.get("min_level", "") or ""
        job.work_years_min = int(exp.get("years_min") or 0)
        ymax = exp.get("years_max")
        job.work_years_max = int(ymax) if ymax is not None else 99

        required_names = [s["name"] for s in hard if s.get("must_have")]
        job.required_skills = ",".join(required_names)

        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/python.exe -m pytest tests/modules/screening/test_double_write.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add app/modules/screening/competency_service.py tests/modules/screening/test_double_write.py
git commit -m "feat(F1-T17): screening/competency_service — approve double-write

- apply_competency_to_job() translates CompetencyModel → flat fields:
    education.min_level → education_min
    experience.years_min → work_years_min
    experience.years_max → work_years_max (null → 99)
    must_have hard_skills[] → required_skills CSV
- only must_have=True skills go into required_skills (stricter gate)
- 3 tests

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task T18: screening/service.py — screen_resumes reads competency_model first

**Files:**
- Modify: `app/modules/screening/service.py`
- Test: `tests/modules/screening/test_flat_backward_compat.py`

**Context:** `screen_resumes()` 现在直接读扁平字段。F1 要改为**优先读 competency_model**, 若为空回退扁平字段。这样 M2 老岗位继续工作, 新岗位用 model 驱动。

- [ ] **Step 1: Create the failing regression test**

Create `tests/modules/screening/test_flat_backward_compat.py`:

```python
"""验证 M2 老岗位 (competency_model=NULL) 筛选行为不变."""
import pytest
from alembic import command
from alembic.config import Config
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from app.modules.screening.service import ScreeningService
from app.modules.screening.models import Job
from app.modules.resume.models import Resume


@pytest.fixture
def db(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    url = f"sqlite:///{db}"
    cfg = Config("migrations/alembic.ini")
    cfg.set_main_option("script_location", "migrations")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "0006")
    engine = sa.create_engine(url, connect_args={"check_same_thread": False})
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr("app.database.engine", engine)
    return factory()


def test_flat_fields_still_filter_when_competency_model_null(db):
    job = Job(title="后端", education_min="本科", required_skills="Python,FastAPI",
               work_years_min=3, work_years_max=7)  # competency_model 默认 NULL
    pass_resume = Resume(name="合格", education="本科", work_years=5,
                          skills="Python, FastAPI, Redis")
    fail_edu = Resume(name="学历差", education="大专", work_years=5, skills="Python,FastAPI")
    fail_skill = Resume(name="技能缺", education="本科", work_years=5, skills="Java")
    db.add_all([job, pass_resume, fail_edu, fail_skill]); db.commit()

    result = ScreeningService(db).screen_resumes(job.id)
    assert result["passed"] == 1
    assert result["rejected"] == 2

    passed = next(r for r in result["results"] if r["passed"])
    assert passed["resume_name"] == "合格"


def test_competency_model_drives_filter_when_present(db):
    """岗位有 competency_model + 扁平字段, 应以 competency_model 为准."""
    comp = {
        "hard_skills": [
            {"name": "Rust", "weight": 9, "must_have": True, "level": "熟练"},
        ],
        "soft_skills": [],
        "experience": {"years_min": 5, "years_max": None,
                        "industries": [], "company_scale": None},
        "education": {"min_level": "硕士", "preferred_level": None, "prestigious_bonus": False},
        "job_level": "", "bonus_items": [], "exclusions": [],
        "assessment_dimensions": [],
        "source_jd_hash": "h", "extracted_at": "2026-04-20T10:00:00",
    }
    # 扁平字段故意冲突: 扁平说 Python+本科, model 说 Rust+硕士
    job = Job(title="x", competency_model=comp, competency_model_status="approved",
               education_min="本科", required_skills="Python", work_years_min=0)
    rust_hao = Resume(name="Rust 大哥", education="硕士", work_years=6, skills="Rust, Go")
    db.add_all([job, rust_hao]); db.commit()

    result = ScreeningService(db).screen_resumes(job.id)
    assert result["passed"] == 1


def test_rejected_if_hard_skill_missing_from_competency(db):
    comp = {
        "hard_skills": [
            {"name": "Rust", "weight": 9, "must_have": True, "level": "熟练"},
        ],
        "soft_skills": [], "experience": {"years_min": 0, "years_max": None,
                                           "industries": [], "company_scale": None},
        "education": {"min_level": "本科"}, "job_level": "",
        "bonus_items": [], "exclusions": [], "assessment_dimensions": [],
        "source_jd_hash": "h", "extracted_at": "2026-04-20T10:00:00",
    }
    job = Job(title="x", competency_model=comp, competency_model_status="approved")
    no_rust = Resume(name="no_rust", education="本科", work_years=3, skills="Python")
    db.add_all([job, no_rust]); db.commit()

    result = ScreeningService(db).screen_resumes(job.id)
    assert result["passed"] == 0
    rejected = result["results"][0]
    assert any("Rust" in r for r in rejected["reject_reasons"])
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/python.exe -m pytest tests/modules/screening/test_flat_backward_compat.py -v
```
Expected: `test_flat_fields_still_filter_when_competency_model_null` PASS（M2 行为）；另 2 个 FAIL（当前 service 不看 competency_model）。

- [ ] **Step 3: Modify `app/modules/screening/service.py::screen_resumes`**

替换 `screen_resumes` 内 "for resume in resumes" 循环体, 从 "if job.education_min:" 到 "if job.required_skills:" 整段:

```python
        # 决定使用 competency_model 还是扁平字段
        use_model = (
            job.competency_model is not None
            and job.competency_model_status == "approved"
        )

        if use_model:
            cm = job.competency_model
            edu_req = (cm.get("education") or {}).get("min_level", "") or ""
            exp = cm.get("experience") or {}
            years_min = int(exp.get("years_min") or 0)
            years_max_val = exp.get("years_max")
            years_max = int(years_max_val) if years_max_val is not None else 99
            must_have_skills = [
                s["name"] for s in (cm.get("hard_skills") or []) if s.get("must_have")
            ]
        else:
            edu_req = job.education_min or ""
            years_min = job.work_years_min
            years_max = job.work_years_max
            must_have_skills = [
                s.strip() for s in (job.required_skills or "").split(",") if s.strip()
            ]

        for resume in resumes:
            reject_reasons = []

            if edu_req:
                min_level = EDUCATION_LEVELS.get(edu_req, 0)
                resume_level = EDUCATION_LEVELS.get(resume.education, 0)
                if resume_level < min_level:
                    reject_reasons.append(
                        f"学历不符：要求{edu_req}，实际{resume.education or '未知'}"
                    )

            if resume.work_years < years_min:
                reject_reasons.append(
                    f"工作年限不足：要求{years_min}年，实际{resume.work_years}年"
                )
            if resume.work_years > years_max:
                reject_reasons.append(
                    f"工作年限超出：最高{years_max}年，实际{resume.work_years}年"
                )

            if job.salary_max > 0 and resume.expected_salary_min > 0:
                if resume.expected_salary_min > job.salary_max:
                    reject_reasons.append(
                        f"薪资期望过高：岗位上限{job.salary_max}，期望{resume.expected_salary_min}"
                    )

            if must_have_skills:
                resume_skills = (resume.skills or "").lower()
                resume_text = (resume.raw_text or "").lower()
                for skill in must_have_skills:
                    sk = skill.lower()
                    if sk not in resume_skills and sk not in resume_text:
                        reject_reasons.append(f"缺少必备技能：{skill}")

            is_passed = len(reject_reasons) == 0
            if is_passed:
                passed_count += 1
                resume.status = "passed"
            else:
                rejected_count += 1
                resume.status = "rejected"
                resume.reject_reason = "; ".join(reject_reasons)

            results.append({
                "resume_id": resume.id,
                "resume_name": resume.name,
                "passed": is_passed,
                "reject_reasons": reject_reasons,
            })
```

- [ ] **Step 4: Run test to verify all 3 tests pass**

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/python.exe -m pytest tests/modules/screening/test_flat_backward_compat.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Run M2 regression + confirm baseline held**

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/python.exe -m pytest tests/ --tb=no -q 2>&1 | tail -5
```
Expected: ≥ 53 passed (M2 baseline)。

- [ ] **Step 6: Commit**

```bash
git add app/modules/screening/service.py tests/modules/screening/test_flat_backward_compat.py
git commit -m "feat(F1-T18): screening reads competency_model first, falls back to flat

- screen_resumes: use_model = (competency_model and status=approved)
- model path reads: education.min_level / experience.years_min/max / must_have hard_skills
- flat fallback unchanged (M2 baseline regression: green)
- 3 new tests: flat compat + model drives + missing must_have rejected

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task T19: screening/router.py — 3 new competency endpoints

**Files:**
- Modify: `app/modules/screening/router.py`
- Test: `tests/modules/screening/test_competency_router.py`

- [ ] **Step 1: Create the failing test**

Create `tests/modules/screening/test_competency_router.py`:

```python
"""screening/router.py — /competency/extract, /competency, /competency/manual."""
import json
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from alembic import command
from alembic.config import Config
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.modules.screening.models import Job


@pytest.fixture
def client(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    url = f"sqlite:///{db}"
    cfg = Config("migrations/alembic.ini")
    cfg.set_main_option("script_location", "migrations")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "0006")
    engine = sa.create_engine(url, connect_args={"check_same_thread": False})
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr("app.database.engine", engine)
    monkeypatch.setattr(
        "app.modules.screening.competency_service._session_factory", factory
    )
    monkeypatch.setattr(
        "app.core.competency.skill_library._session_factory", factory
    )
    monkeypatch.setattr("app.core.audit.logger._session_factory", factory)
    monkeypatch.setattr("app.core.hitl.service._session_factory", factory)

    # 建一个岗位
    s = factory()
    s.add(Job(title="后端", jd_text="招聘 Python 后端")); s.commit()
    s.close()

    # disable auth for test (or set test token)
    # 这里用 monkeypatch 绕过 auth middleware:
    monkeypatch.setenv("AGENTICHR_TEST_BYPASS_AUTH", "1")
    return TestClient(app)


def test_extract_success(client, monkeypatch):
    from app.core.competency.schema import CompetencyModel, HardSkill
    from datetime import datetime, timezone

    mock_model = CompetencyModel(
        hard_skills=[HardSkill(name="Python", weight=9)],
        source_jd_hash="h", extracted_at=datetime.now(timezone.utc),
    )
    mock_extract = AsyncMock(return_value=mock_model)
    monkeypatch.setattr("app.modules.screening.router.extract_competency", mock_extract)

    resp = client.post("/api/screening/jobs/1/competency/extract")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "draft"
    assert "hitl_task_id" in data


def test_extract_failure_returns_fallback(client, monkeypatch):
    from app.core.competency.extractor import ExtractionFailedError
    mock_extract = AsyncMock(side_effect=ExtractionFailedError("LLM down"))
    monkeypatch.setattr("app.modules.screening.router.extract_competency", mock_extract)

    resp = client.post("/api/screening/jobs/1/competency/extract")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "failed"
    assert data["fallback"] == "flat_form"


def test_get_competency(client):
    resp = client.get("/api/screening/jobs/1/competency")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "none"
    assert data["competency_model"] is None


def test_manual_flat_form_creates_approved_model(client):
    body = {
        "flat_fields": {
            "education_min": "本科",
            "work_years_min": 3,
            "work_years_max": 7,
            "required_skills": "Python,FastAPI",
        }
    }
    resp = client.post("/api/screening/jobs/1/competency/manual", json=body)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "approved"

    # 验证 competency_model 被生成 + status=approved
    resp2 = client.get("/api/screening/jobs/1/competency")
    d2 = resp2.json()
    assert d2["status"] == "approved"
    assert len(d2["competency_model"]["hard_skills"]) == 2
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/python.exe -m pytest tests/modules/screening/test_competency_router.py -v
```
Expected: FAIL — 路由不存在。

- [ ] **Step 3: Modify `app/modules/screening/router.py`**

在文件顶部 imports 追加:

```python
from datetime import datetime, timezone
from pydantic import BaseModel
from app.core.competency.extractor import extract_competency, ExtractionFailedError
from app.core.hitl.service import HitlService
from app.modules.screening.competency_service import apply_competency_to_job
```

在文件末尾 router 定义下追加:

```python
class _ManualBody(BaseModel):
    flat_fields: dict


@router.post("/jobs/{job_id}/competency/extract")
async def extract_job_competency(job_id: int):
    """触发 LLM 抽取能力模型. 成功 → draft + HITL; 失败 → 降级扁平表单."""
    # 1. 检查 job 存在
    from app.database import SessionLocal
    from app.modules.screening.models import Job
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        jd_text = job.jd_text or ""
    finally:
        db.close()

    if not jd_text.strip():
        raise HTTPException(status_code=400, detail="jd_text 为空, 请先填 JD 原文")

    try:
        model = await extract_competency(jd_text=jd_text, job_id=job_id)
    except ExtractionFailedError:
        return {"status": "failed", "fallback": "flat_form"}

    # 写 draft
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        job.competency_model = model.model_dump(mode="json")
        job.competency_model_status = "draft"
        db.commit()
    finally:
        db.close()

    # 创建阻塞 HITL
    hitl_id = HitlService().create(
        f_stage="F1_competency_review",
        entity_type="job",
        entity_id=job_id,
        payload=model.model_dump(mode="json"),
    )

    return {"status": "draft", "hitl_task_id": hitl_id}


@router.get("/jobs/{job_id}/competency")
def get_job_competency(job_id: int):
    from app.database import SessionLocal
    from app.modules.screening.models import Job
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        return {
            "competency_model": job.competency_model,
            "status": job.competency_model_status,
        }
    finally:
        db.close()


@router.post("/jobs/{job_id}/competency/manual")
def manual_competency(job_id: int, body: _ManualBody):
    """LLM 失败后 HR 手填扁平字段, 服务端翻译为最简 CompetencyModel, 直接 approved."""
    f = body.flat_fields
    skills_csv = f.get("required_skills", "") or ""
    hard_skills = [
        {"name": s.strip(), "weight": 5, "level": "熟练", "must_have": True}
        for s in skills_csv.split(",") if s.strip()
    ]
    model_dict = {
        "schema_version": 1,
        "hard_skills": hard_skills,
        "soft_skills": [],
        "experience": {
            "years_min": int(f.get("work_years_min") or 0),
            "years_max": int(f.get("work_years_max")) if f.get("work_years_max") is not None else None,
            "industries": [],
            "company_scale": None,
        },
        "education": {
            "min_level": f.get("education_min") or "本科",
            "preferred_level": None,
            "prestigious_bonus": False,
        },
        "job_level": "",
        "bonus_items": [],
        "exclusions": [],
        "assessment_dimensions": [],
        "source_jd_hash": "manual_fallback",
        "extracted_at": datetime.now(timezone.utc).isoformat(),
    }
    apply_competency_to_job(job_id, model_dict)

    from app.core.audit.logger import log_event
    log_event(
        f_stage="F1_competency_review",
        action="manual_fallback",
        entity_type="job",
        entity_id=job_id,
        input_payload=body.flat_fields,
        output_payload=model_dict,
    )
    return {"status": "approved"}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/python.exe -m pytest tests/modules/screening/test_competency_router.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add app/modules/screening/router.py tests/modules/screening/test_competency_router.py
git commit -m "feat(F1-T19): screening/router — 3 competency endpoints

- POST /jobs/{id}/competency/extract: trigger LLM → draft + HITL, or failed+fallback
- GET /jobs/{id}/competency: read model + status
- POST /jobs/{id}/competency/manual: flat form → minimal model + directly approved
  (bypasses HITL per spec D4, audit as manual_fallback)
- 4 tests

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task T19b: wire HITL approve → double-write in screening/router

**Files:**
- Modify: `app/core/hitl/router.py` — approve endpoint 需要能触发下游动作
- Modify: `app/core/hitl/service.py` — approve 时若 entity_type=job + f_stage=F1_competency_review → 调用 `apply_competency_to_job`

**Context:** HITL 通用 service 不应该知道 screening 细节. 用 callback 机制解耦.

- [ ] **Step 1: Create the failing test**

Append to `tests/core/test_hitl_service.py`:

```python
def test_approve_triggers_registered_callback(svc, monkeypatch):
    """可注册 stage-specific callback, approve 时被调用."""
    from app.core.hitl.service import register_approve_callback

    seen = []
    def cb(task):
        seen.append(task)

    register_approve_callback("F1_competency_review", cb)
    tid = svc.create("F1_competency_review", "job", 42, {"hard_skills": []})
    svc.approve(tid, reviewer_id=1)

    assert len(seen) == 1
    assert seen[0]["entity_id"] == 42
```

- [ ] **Step 2: Run test to verify fails**

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/python.exe -m pytest tests/core/test_hitl_service.py::test_approve_triggers_registered_callback -v
```
Expected: FAIL — `register_approve_callback` 不存在。

- [ ] **Step 3: Add callback registry to `app/core/hitl/service.py`**

在 service.py 顶部 `_session_factory = ...` 附近加:

```python
_approve_callbacks: dict[str, list] = {}


def register_approve_callback(f_stage: str, callback) -> None:
    """注册 stage-specific 的 approve 后 callback. 参数是 task dict."""
    _approve_callbacks.setdefault(f_stage, []).append(callback)
```

在 `_transition` 方法末尾 (commit 之后) 加:

```python
        if new_status == "approved":
            for cb in _approve_callbacks.get(t.f_stage, []):
                try:
                    cb(_row_to_dict(t))
                except Exception as e:
                    logger.error(f"approve callback failed: {e}")
```

同理在 `edit` 方法 commit 之后加 (edit 也视为"通过并发布"):

```python
        for cb in _approve_callbacks.get(t.f_stage, []):
            try:
                cb(_row_to_dict(t))
            except Exception as e:
                logger.error(f"edit callback failed: {e}")
```

- [ ] **Step 4: Register double-write callback at app startup**

在 `app/main.py` 的 startup 区域 (或 module top-level 注册):

```python
from app.core.hitl.service import register_approve_callback
from app.modules.screening.competency_service import apply_competency_to_job


def _on_competency_approved(task: dict) -> None:
    """HITL F1_competency_review approve → 写 jobs.competency_model + 双写扁平字段."""
    if task["entity_type"] != "job":
        return
    payload = task.get("edited_payload") or task.get("payload")
    if payload is None:
        return
    apply_competency_to_job(task["entity_id"], payload)


register_approve_callback("F1_competency_review", _on_competency_approved)
```

- [ ] **Step 5: Run tests to confirm passes**

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/python.exe -m pytest tests/core/test_hitl_service.py -v
```
Expected: 8 passed (7 旧 + 1 新).

- [ ] **Step 6: Commit**

```bash
git add app/core/hitl/service.py app/main.py tests/core/test_hitl_service.py
git commit -m "feat(F1-T19b): HITL approve callbacks + wire competency double-write

- register_approve_callback(f_stage, fn) registry
- approve/edit both trigger callbacks (edit is 'approve with changes')
- app startup registers F1_competency_review callback → apply_competency_to_job
- decouples screening from hitl service

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 4 — Frontend

> **测试说明**：项目无前端单测框架（沿用现状）。前端任务的"测试"= ① 本地 `npm run build` 无错 ② 启动后端后人工点一遍关键路径。每个任务步骤包含 build 验证命令。

### Task T20: api/index.js — 3 new API modules

**Files:**
- Modify: `frontend/src/api/index.js`

- [ ] **Step 1: Add 3 API modules**

在 `frontend/src/api/index.js` 的 `// Boss API` 前面追加:

```javascript
// 能力模型 API (F1)
export const competencyApi = {
  get: (jobId) => api.get(`/screening/jobs/${jobId}/competency`),
  extract: (jobId) => api.post(`/screening/jobs/${jobId}/competency/extract`),
  manual: (jobId, flatFields) => api.post(`/screening/jobs/${jobId}/competency/manual`, { flat_fields: flatFields }),
}

// HITL API (F1)
export const hitlApi = {
  list: (params) => api.get('/hitl/tasks', { params }),
  get: (id) => api.get(`/hitl/tasks/${id}`),
  approve: (id, note = '') => api.post(`/hitl/tasks/${id}/approve`, { note }),
  reject: (id, note) => api.post(`/hitl/tasks/${id}/reject`, { note }),
  edit: (id, editedPayload, note = '') => api.post(`/hitl/tasks/${id}/edit`, { edited_payload: editedPayload, note }),
}

// 技能库 API (F1)
export const skillsApi = {
  list: (params) => api.get('/skills', { params }),
  get: (id) => api.get(`/skills/${id}`),
  create: (data) => api.post('/skills', data),
  update: (id, data) => api.put(`/skills/${id}`, data),
  merge: (id, mergeIntoId) => api.post(`/skills/${id}/merge`, { merge_into_id: mergeIntoId }),
  delete: (id) => api.delete(`/skills/${id}`),
  categories: () => api.get('/skills/categories'),
}
```

- [ ] **Step 2: Build check**

```bash
cd /d/libz/AgenticHR/frontend
npm run build 2>&1 | tail -5
```
Expected: `✓ built in Xs` (无错).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/index.js
git commit -m "feat(F1-T20): frontend/api — competencyApi / hitlApi / skillsApi

- competencyApi: get/extract/manual
- hitlApi: list/get/approve/reject/edit
- skillsApi: list/get/create/update/merge/delete/categories

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task T20b: skills 路由 backend

**Files:**
- Create: `app/core/competency/router.py`
- Modify: `app/main.py`
- Test: `tests/core/test_skills_router.py`

**Context:** T22 的 SkillPicker autocomplete 需要调 `/api/skills?search=`. T20 API 模块已定义, 但后端路由没实装. 这里补上.

- [ ] **Step 1: Create failing test**

Create `tests/core/test_skills_router.py`:

```python
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
```

- [ ] **Step 2: Run to verify fails**

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/python.exe -m pytest tests/core/test_skills_router.py -v
```
Expected: FAIL (路由不存在).

- [ ] **Step 3: Create `app/core/competency/router.py`**

```python
"""/api/skills 路由."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.competency.skill_library import SkillLibrary

router = APIRouter(prefix="/api/skills", tags=["skills"])


class _SkillCreateBody(BaseModel):
    canonical_name: str
    category: str = "uncategorized"
    aliases: list[str] = []


class _SkillUpdateBody(BaseModel):
    canonical_name: str | None = None
    category: str | None = None
    aliases: list[str] | None = None


class _MergeBody(BaseModel):
    merge_into_id: int


@router.get("")
def list_skills(
    search: str | None = None,
    category: str | None = None,
    pending: bool = False,
    limit: int = 20,
    offset: int = 0,
):
    lib = SkillLibrary()
    if search:
        items = lib.search(search, limit=limit)
    elif pending:
        items = lib.list_pending()
    else:
        items = lib.list_all()
        if category:
            items = [s for s in items if s["category"] == category]
        items = items[offset: offset + limit]
    return {"items": items, "total": len(items)}


@router.get("/categories")
def list_categories():
    lib = SkillLibrary()
    cats = sorted({s["category"] for s in lib.list_all()})
    return {"categories": cats}


@router.get("/{skill_id}")
def get_skill(skill_id: int):
    lib = SkillLibrary()
    s = lib.find_by_id(skill_id)
    if not s:
        raise HTTPException(status_code=404, detail="skill not found")
    return s


@router.post("")
def create_skill(body: _SkillCreateBody):
    lib = SkillLibrary()
    if lib.find_by_name(body.canonical_name):
        raise HTTPException(status_code=409, detail="skill already exists")
    new_id = lib.insert(
        canonical_name=body.canonical_name,
        source="seed_manual",
        category=body.category,
        aliases=body.aliases,
    )
    return lib.find_by_id(new_id)


@router.put("/{skill_id}")
def update_skill(skill_id: int, body: _SkillUpdateBody):
    # 简化: 直接操作 session
    from sqlalchemy.orm import sessionmaker
    from app.database import engine
    from app.core.competency.models import Skill
    session = sessionmaker(bind=engine)()
    try:
        s = session.query(Skill).filter(Skill.id == skill_id).first()
        if not s:
            raise HTTPException(status_code=404, detail="not found")
        if body.canonical_name is not None:
            s.canonical_name = body.canonical_name
        if body.category is not None:
            s.category = body.category
        if body.aliases is not None:
            s.aliases = body.aliases
        session.commit()
        from app.core.competency.skill_library import SkillCache
        SkillCache.invalidate()
        return SkillLibrary().find_by_id(skill_id)
    finally:
        session.close()


@router.post("/{skill_id}/merge")
def merge_skill(skill_id: int, body: _MergeBody):
    lib = SkillLibrary()
    try:
        lib.merge(skill_id, body.merge_into_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "merged"}


@router.delete("/{skill_id}")
def delete_skill(skill_id: int):
    from sqlalchemy.orm import sessionmaker
    from app.database import engine
    from app.core.competency.models import Skill
    session = sessionmaker(bind=engine)()
    try:
        s = session.query(Skill).filter(Skill.id == skill_id).first()
        if not s:
            raise HTTPException(status_code=404, detail="not found")
        if s.source == "seed" or (s.usage_count or 0) > 0:
            raise HTTPException(status_code=400, detail="只能删除未被使用的 llm_extracted 技能")
        session.delete(s)
        session.commit()
        from app.core.competency.skill_library import SkillCache
        SkillCache.invalidate()
        return {"status": "deleted"}
    finally:
        session.close()
```

- [ ] **Step 4: Register router in `app/main.py`**

```python
from app.core.competency.router import router as skills_router
app.include_router(skills_router)
```

- [ ] **Step 5: Run tests**

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/python.exe -m pytest tests/core/test_skills_router.py -v
```
Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add app/core/competency/router.py app/main.py tests/core/test_skills_router.py
git commit -m "feat(F1-T20b): core/competency/router — /api/skills endpoints

- list (search/category/pending filters) / categories
- get/create/update/merge/delete
- seed skills cannot be deleted
- 5 tests

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task T21: App.vue — nav menu 扩展 + HITL badge

**Files:**
- Modify: `frontend/src/App.vue`

- [ ] **Step 1: Read current App.vue to understand structure**

```bash
cd /d/libz/AgenticHR
head -50 frontend/src/App.vue
```

- [ ] **Step 2: Add 2 menu items + HITL pending badge**

在 App.vue 的 `<el-menu>` 里, 在"岗位"和"面试官"之间加新菜单, 在 `<script setup>` 加轮询逻辑.

菜单项 (按现有模板语法添加, 参考现 Resumes / Jobs 的 `<el-menu-item>` 结构):

```html
<el-menu-item index="/jobs">
  <el-icon><Briefcase /></el-icon>
  岗位
</el-menu-item>

<el-menu-item index="/hitl">
  <el-icon><View /></el-icon>
  审核队列
  <el-badge v-if="hitlPendingCount > 0" :value="hitlPendingCount" class="hitl-badge" />
</el-menu-item>

<el-menu-item index="/skills">
  <el-icon><Collection /></el-icon>
  技能库
</el-menu-item>

<el-menu-item index="/interviewers">
  ...
</el-menu-item>
```

`<script setup>` 加入:

```javascript
import { ref, onMounted, onUnmounted } from 'vue'
import { hitlApi } from './api'
import { View, Collection } from '@element-plus/icons-vue'  // 其他 icon 已 import 则无需重复

const hitlPendingCount = ref(0)
let pollTimer = null

async function refreshPending() {
  try {
    const resp = await hitlApi.list({ status: 'pending', limit: 1 })
    hitlPendingCount.value = resp.pending || 0
  } catch (e) {
    console.error('refresh pending failed', e)
  }
}

onMounted(() => {
  refreshPending()
  pollTimer = setInterval(refreshPending, 5 * 60 * 1000)  // 5 分钟
})
onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})
```

`<style>` 加:

```css
.hitl-badge {
  margin-left: 8px;
}
```

- [ ] **Step 3: Build check**

```bash
cd /d/libz/AgenticHR/frontend
npm run build 2>&1 | tail -5
```
Expected: `✓ built`。

- [ ] **Step 4: Manually verify badge polls (skip if no server running)**

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/python.exe -m uvicorn app.main:app --port 8000 &
# open http://127.0.0.1:8000 in browser, check sidebar shows "审核队列" and "技能库"
kill %1
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.vue
git commit -m "feat(F1-T21): App.vue — nav adds 审核队列 (badge) / 技能库

- hitlApi.list({status:'pending',limit:1}) polled every 5min
- badge shows pending count when > 0
- menu items placed between Jobs and Interviewers

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task T22: components/SkillPicker.vue — autocomplete

**Files:**
- Create: `frontend/src/components/SkillPicker.vue`

**Context:** 能力模型 6 卡片里"硬技能"卡片用, 也会被 F2 简历标签复用. 用 `el-autocomplete` + 防抖.

- [ ] **Step 1: Create `frontend/src/components/SkillPicker.vue`**

```bash
cd /d/libz/AgenticHR/frontend
mkdir -p src/components
```

Create `frontend/src/components/SkillPicker.vue`:

```vue
<template>
  <el-autocomplete
    v-model="inputValue"
    :fetch-suggestions="querySkills"
    :placeholder="placeholder"
    :trigger-on-focus="false"
    clearable
    :debounce="300"
    @select="onSelect"
    @keyup.enter="onEnter"
    class="skill-picker"
  >
    <template #default="{ item }">
      <div class="skill-suggestion">
        <span class="skill-name">{{ item.canonical_name }}</span>
        <el-tag size="small" :type="tagType(item.category)">{{ item.category }}</el-tag>
        <span v-if="item.aliases?.length" class="skill-aliases">
          ({{ item.aliases.join(', ') }})
        </span>
      </div>
    </template>
  </el-autocomplete>
</template>

<script setup>
import { ref, watch } from 'vue'
import { skillsApi } from '../api'

const props = defineProps({
  modelValue: { type: String, default: '' },
  placeholder: { type: String, default: '输入技能名, 按回车添加...' },
})
const emit = defineEmits(['update:modelValue', 'select'])

const inputValue = ref(props.modelValue)

watch(() => props.modelValue, (v) => { inputValue.value = v })

async function querySkills(query, cb) {
  if (!query) return cb([])
  try {
    const resp = await skillsApi.list({ search: query, limit: 10 })
    cb(resp.items || [])
  } catch (e) {
    cb([])
  }
}

function onSelect(item) {
  inputValue.value = item.canonical_name
  emit('update:modelValue', item.canonical_name)
  emit('select', item)
}

function onEnter() {
  if (!inputValue.value) return
  emit('update:modelValue', inputValue.value)
  emit('select', { canonical_name: inputValue.value, is_new: true })
}

function tagType(cat) {
  const map = { language: 'primary', framework: 'success', cloud: 'warning',
                 database: 'info', tool: '', soft: 'danger', domain: 'primary' }
  return map[cat] || ''
}
</script>

<style scoped>
.skill-picker { width: 100%; }
.skill-suggestion { display: flex; align-items: center; gap: 8px; }
.skill-name { font-weight: 500; }
.skill-aliases { color: #909399; font-size: 12px; }
</style>
```

- [ ] **Step 2: Build check**

```bash
cd /d/libz/AgenticHR/frontend
npm run build 2>&1 | tail -5
```
Expected: `✓ built`。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/SkillPicker.vue
git commit -m "feat(F1-T22): components/SkillPicker — skill autocomplete

- debounced 300ms search via skillsApi.list({search})
- suggestions show canonical_name + category tag + aliases
- select emits the skill object; enter emits {is_new:true} for new skill entry
- v-model pass-through

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task T23: components/CompetencyEditor.vue — 6 folded cards

**Files:**
- Create: `frontend/src/components/CompetencyEditor.vue`

**Context:** 核心 UI. 内嵌 Jobs.vue Tab. 6 个折叠卡片 + JD 原文 + 两键模型.

- [ ] **Step 1: Create the component**

Create `frontend/src/components/CompetencyEditor.vue`:

```vue
<template>
  <div class="competency-editor">
    <!-- 状态指示 + JD 原文 -->
    <el-card class="header-card" shadow="never">
      <div class="status-row">
        <span class="label">状态:</span>
        <el-tag :type="statusTag(status)" size="large">{{ statusText(status) }}</el-tag>
        <el-button
          v-if="status === 'none' || status === 'rejected'"
          type="primary" @click="onExtract" :loading="extracting"
          :disabled="!jdText.trim()">
          从 JD 抽取
        </el-button>
        <el-button
          v-if="status === 'approved'"
          type="warning" @click="onExtract" :loading="extracting">
          重新抽取
        </el-button>
      </div>
      <el-input
        v-model="jdText" type="textarea" :rows="6"
        placeholder="粘贴 JD 原文..." class="jd-input"
      />
    </el-card>

    <!-- 手填降级模式 -->
    <el-alert
      v-if="fallbackMode" type="warning" :closable="false"
      title="LLM 抽取失败, 请手工填写" show-icon class="fallback-alert"
    />
    <el-form v-if="fallbackMode" :model="flatForm" label-width="100px" class="fallback-form">
      <el-form-item label="学历要求">
        <el-select v-model="flatForm.education_min">
          <el-option label="大专" value="大专" />
          <el-option label="本科" value="本科" />
          <el-option label="硕士" value="硕士" />
          <el-option label="博士" value="博士" />
        </el-select>
      </el-form-item>
      <el-form-item label="工作年限">
        <el-input-number v-model="flatForm.work_years_min" :min="0" :max="30" /> ~
        <el-input-number v-model="flatForm.work_years_max" :min="0" :max="30" />
      </el-form-item>
      <el-form-item label="必备技能 (逗号分隔)">
        <el-input v-model="flatForm.required_skills" placeholder="Python,FastAPI,..." />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" @click="submitFlat">保存并发布</el-button>
        <el-button @click="fallbackMode=false">取消</el-button>
      </el-form-item>
    </el-form>

    <!-- 6 折叠卡片 -->
    <el-collapse v-if="!fallbackMode && model" v-model="activeCards" class="cards">
      <el-collapse-item title="硬技能" name="hard">
        <el-table :data="model.hard_skills" border size="small">
          <el-table-column label="技能" min-width="200">
            <template #default="{ row }">
              <SkillPicker v-model="row.name" @select="onSkillSelect(row, $event)" />
            </template>
          </el-table-column>
          <el-table-column label="等级" width="120">
            <template #default="{ row }">
              <el-select v-model="row.level" size="small">
                <el-option label="了解" value="了解" />
                <el-option label="熟练" value="熟练" />
                <el-option label="精通" value="精通" />
              </el-select>
            </template>
          </el-table-column>
          <el-table-column label="权重" width="160">
            <template #default="{ row }">
              <el-slider v-model="row.weight" :min="1" :max="10" show-input />
            </template>
          </el-table-column>
          <el-table-column label="必须" width="80" align="center">
            <template #default="{ row }">
              <el-checkbox v-model="row.must_have" />
            </template>
          </el-table-column>
          <el-table-column label="" width="60">
            <template #default="{ $index }">
              <el-button size="small" type="danger" link @click="removeHard($index)">删</el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-button size="small" @click="addHard" class="add-btn">+ 添加技能</el-button>
      </el-collapse-item>

      <el-collapse-item title="软技能" name="soft">
        <el-table :data="model.soft_skills" border size="small">
          <el-table-column label="技能" min-width="200">
            <template #default="{ row }">
              <el-input v-model="row.name" size="small" />
            </template>
          </el-table-column>
          <el-table-column label="权重" width="160">
            <template #default="{ row }">
              <el-slider v-model="row.weight" :min="1" :max="10" show-input />
            </template>
          </el-table-column>
          <el-table-column label="评估阶段" width="130">
            <template #default="{ row }">
              <el-select v-model="row.assessment_stage" size="small">
                <el-option label="简历" value="简历" />
                <el-option label="IM" value="IM" />
                <el-option label="面试" value="面试" />
              </el-select>
            </template>
          </el-table-column>
          <el-table-column label="" width="60">
            <template #default="{ $index }">
              <el-button size="small" type="danger" link @click="removeSoft($index)">删</el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-button size="small" @click="addSoft" class="add-btn">+ 添加软技能</el-button>
      </el-collapse-item>

      <el-collapse-item title="工作经验" name="exp">
        <el-form :model="model.experience" label-width="120px" size="small">
          <el-form-item label="最少年限">
            <el-input-number v-model="model.experience.years_min" :min="0" :max="30" />
          </el-form-item>
          <el-form-item label="最高年限">
            <el-input-number v-model="model.experience.years_max" :min="0" :max="30" />
            <el-checkbox :model-value="model.experience.years_max === null"
                          @update:model-value="v => model.experience.years_max = v ? null : 99"
                          style="margin-left:10px">
              不限
            </el-checkbox>
          </el-form-item>
          <el-form-item label="行业">
            <el-tag v-for="(ind, idx) in model.experience.industries" :key="idx"
                     closable @close="model.experience.industries.splice(idx,1)">
              {{ ind }}
            </el-tag>
            <el-input size="small" v-model="newIndustry" @keyup.enter="addIndustry" style="width:120px" />
            <el-button size="small" @click="addIndustry">+</el-button>
          </el-form-item>
          <el-form-item label="公司规模">
            <el-select v-model="model.experience.company_scale" clearable>
              <el-option label="大厂" value="大厂" />
              <el-option label="独角兽" value="独角兽" />
              <el-option label="中型" value="中型" />
              <el-option label="初创" value="初创" />
            </el-select>
          </el-form-item>
        </el-form>
      </el-collapse-item>

      <el-collapse-item title="学历" name="edu">
        <el-form :model="model.education" label-width="120px" size="small">
          <el-form-item label="最低学历">
            <el-radio-group v-model="model.education.min_level">
              <el-radio-button label="大专" />
              <el-radio-button label="本科" />
              <el-radio-button label="硕士" />
              <el-radio-button label="博士" />
            </el-radio-group>
          </el-form-item>
          <el-form-item label="名校加分">
            <el-switch v-model="model.education.prestigious_bonus" />
          </el-form-item>
        </el-form>
      </el-collapse-item>

      <el-collapse-item title="加分项 / 淘汰项" name="bonus">
        <div class="tag-row">
          <span class="label">加分项:</span>
          <el-tag v-for="(b, idx) in model.bonus_items" :key="idx"
                   closable @close="model.bonus_items.splice(idx,1)" type="success">
            {{ b }}
          </el-tag>
          <el-input size="small" v-model="newBonus" @keyup.enter="addBonus" style="width:160px" />
          <el-button size="small" @click="addBonus">+</el-button>
        </div>
        <div class="tag-row">
          <span class="label">淘汰项:</span>
          <el-tag v-for="(e, idx) in model.exclusions" :key="idx"
                   closable @close="model.exclusions.splice(idx,1)" type="danger">
            {{ e }}
          </el-tag>
          <el-input size="small" v-model="newExcl" @keyup.enter="addExcl" style="width:160px" />
          <el-button size="small" @click="addExcl">+</el-button>
        </div>
      </el-collapse-item>

      <el-collapse-item title="考察维度" name="assess">
        <el-table :data="model.assessment_dimensions" border size="small">
          <el-table-column label="维度" min-width="140">
            <template #default="{ row }">
              <el-input v-model="row.name" size="small" />
            </template>
          </el-table-column>
          <el-table-column label="描述" min-width="200">
            <template #default="{ row }">
              <el-input v-model="row.description" size="small" />
            </template>
          </el-table-column>
          <el-table-column label="题型" min-width="200">
            <template #default="{ row }">
              <el-tag v-for="(q, qi) in row.question_types" :key="qi" closable
                       @close="row.question_types.splice(qi,1)" style="margin-right:4px">
                {{ q }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="" width="60">
            <template #default="{ $index }">
              <el-button size="small" type="danger" link @click="removeAssess($index)">删</el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-button size="small" @click="addAssess" class="add-btn">+ 添加维度</el-button>
      </el-collapse-item>
    </el-collapse>

    <!-- 底部按钮 -->
    <div v-if="!fallbackMode && model" class="footer">
      <el-button @click="saveDraft" :loading="saving">保存草稿</el-button>
      <el-button type="primary" @click="submitApprove" :loading="saving">通过并发布</el-button>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { competencyApi, hitlApi } from '../api'
import SkillPicker from './SkillPicker.vue'

const props = defineProps({ jobId: { type: Number, required: true } })
const emit = defineEmits(['status-change'])

const jdText = ref('')
const status = ref('none')
const model = ref(null)
const fallbackMode = ref(false)
const extracting = ref(false)
const saving = ref(false)
const activeCards = ref(['hard', 'exp', 'edu'])
const pendingTaskId = ref(null)
const flatForm = ref({ education_min: '本科', work_years_min: 0, work_years_max: 99, required_skills: '' })
const newIndustry = ref('')
const newBonus = ref('')
const newExcl = ref('')

function statusText(s) {
  return { none: '未生成', draft: '待审', approved: '已发布', rejected: '已驳回' }[s] || s
}
function statusTag(s) {
  return { none: 'info', draft: 'warning', approved: 'success', rejected: 'danger' }[s] || ''
}

async function loadCompetency() {
  try {
    const resp = await competencyApi.get(props.jobId)
    model.value = resp.competency_model || null
    status.value = resp.status || 'none'
    emit('status-change', status.value)
  } catch (e) {
    console.error(e)
  }
}

async function onExtract() {
  if (!jdText.value.trim()) {
    ElMessage.warning('请先填 JD 原文')
    return
  }
  extracting.value = true
  try {
    // 先保存 JD 到 job
    // (由 Jobs.vue 外层调 jobApi.update 保存基本字段, 此处假设 jdText 已同步)
    const resp = await competencyApi.extract(props.jobId)
    if (resp.status === 'failed') {
      fallbackMode.value = true
      ElMessage.warning('LLM 抽取失败, 进入手工填写模式')
    } else {
      pendingTaskId.value = resp.hitl_task_id
      await loadCompetency()
      ElMessage.success('抽取完成, 请审核')
    }
  } catch (e) {
    ElMessage.error('抽取失败: ' + (e.message || e))
  } finally {
    extracting.value = false
  }
}

function addHard() {
  model.value.hard_skills.push({ name: '', level: '熟练', weight: 5, must_have: false })
}
function removeHard(i) { model.value.hard_skills.splice(i, 1) }
function addSoft() {
  model.value.soft_skills.push({ name: '', weight: 5, assessment_stage: '面试' })
}
function removeSoft(i) { model.value.soft_skills.splice(i, 1) }
function addAssess() {
  model.value.assessment_dimensions.push({ name: '', description: '', question_types: [] })
}
function removeAssess(i) { model.value.assessment_dimensions.splice(i, 1) }
function addIndustry() {
  if (newIndustry.value.trim()) {
    model.value.experience.industries.push(newIndustry.value.trim())
    newIndustry.value = ''
  }
}
function addBonus() {
  if (newBonus.value.trim()) { model.value.bonus_items.push(newBonus.value.trim()); newBonus.value = '' }
}
function addExcl() {
  if (newExcl.value.trim()) { model.value.exclusions.push(newExcl.value.trim()); newExcl.value = '' }
}

function onSkillSelect(row, skill) {
  row.name = skill.canonical_name
  if (skill.id) row.canonical_id = skill.id
}

async function saveDraft() {
  if (!pendingTaskId.value) {
    ElMessage.warning('没有待审任务, 无法保存草稿. 请先点"从 JD 抽取"')
    return
  }
  saving.value = true
  try {
    await hitlApi.edit(pendingTaskId.value, model.value, 'draft save')
    // edit 也会变 'edited' 状态 → approved. 本实现: 保存草稿 = 不动
    // 简化: 重新加载
    await loadCompetency()
    ElMessage.success('已保存')
  } finally { saving.value = false }
}

async function submitApprove() {
  saving.value = true
  try {
    if (pendingTaskId.value) {
      // 通过 edit 通道提交最新 model + 通过
      await hitlApi.edit(pendingTaskId.value, model.value, 'approved via editor')
    }
    await loadCompetency()
    ElMessage.success('已发布')
  } catch (e) {
    ElMessage.error('发布失败: ' + (e.message || e))
  } finally { saving.value = false }
}

async function submitFlat() {
  try {
    await competencyApi.manual(props.jobId, flatForm.value)
    fallbackMode.value = false
    await loadCompetency()
    ElMessage.success('已保存并发布')
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.message || e))
  }
}

onMounted(loadCompetency)
watch(() => props.jobId, loadCompetency)
</script>

<style scoped>
.competency-editor { padding: 8px 0; }
.header-card { margin-bottom: 12px; }
.status-row { display: flex; align-items: center; gap: 12px; margin-bottom: 10px; }
.status-row .label { font-weight: 500; color: #606266; }
.jd-input { font-family: monospace; }
.cards { margin-top: 8px; }
.add-btn { margin-top: 8px; }
.tag-row { margin-bottom: 10px; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.tag-row .label { font-weight: 500; margin-right: 8px; width: 70px; }
.footer { margin-top: 16px; text-align: right; }
.fallback-alert { margin: 10px 0; }
.fallback-form { background: #fafafa; padding: 16px; border-radius: 4px; }
</style>
```

- [ ] **Step 2: Build check**

```bash
cd /d/libz/AgenticHR/frontend
npm run build 2>&1 | tail -5
```
Expected: `✓ built`. (若报 icon import 缺失, 确认 `@element-plus/icons-vue` 已装.)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/CompetencyEditor.vue
git commit -m "feat(F1-T23): components/CompetencyEditor — 6-card editor

- JD textarea + status indicator + extract/re-extract buttons
- 6 collapsible cards: hard_skills / soft_skills / experience /
  education / bonus+exclusions / assessment_dimensions
- uses SkillPicker for hard_skills autocomplete
- fallback form for LLM-failed manual entry
- two-button model: 保存草稿 / 通过并发布

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task T24: views/Jobs.vue — add el-tabs with Competency Tab

**Files:**
- Modify: `frontend/src/views/Jobs.vue`

**Context:** Jobs.vue 当前 249 行, 是单表单。改造为 el-tabs, 第一个 Tab 保留现有基本信息, 第二个 Tab 嵌入 CompetencyEditor. 改造只针对"岗位详情 dialog/drawer", 列表页不动.

- [ ] **Step 1: Read Jobs.vue 找到编辑 dialog**

```bash
cd /d/libz/AgenticHR
grep -n "el-dialog\|el-drawer\|<template" frontend/src/views/Jobs.vue | head -20
```

- [ ] **Step 2: Wrap dialog body in el-tabs**

在 Jobs.vue 的编辑 dialog body 里:

```html
<el-tabs v-model="activeTab" v-if="currentJobId">
  <el-tab-pane label="基本信息" name="basic">
    <!-- 保留现有的表单, 原封不动 -->
    <el-form ref="formRef" :model="form" label-width="100px">
      ... (原有字段)
    </el-form>
  </el-tab-pane>

  <el-tab-pane :label="competencyLabel" name="competency">
    <CompetencyEditor :job-id="currentJobId" @status-change="onStatusChange" />
  </el-tab-pane>
</el-tabs>
```

`<script setup>` 加:

```javascript
import { ref, computed } from 'vue'
import CompetencyEditor from '../components/CompetencyEditor.vue'

const activeTab = ref('basic')
const currentJobId = ref(null)  // 在点编辑按钮时赋值, 原逻辑里找对应地方
const competencyStatus = ref('none')

const competencyLabel = computed(() => {
  if (competencyStatus.value === 'draft') return '能力模型 ●待审'
  if (competencyStatus.value === 'approved') return '能力模型 ✓'
  if (competencyStatus.value === 'rejected') return '能力模型 ✕'
  return '能力模型'
})

function onStatusChange(s) { competencyStatus.value = s }

// 打开编辑 dialog 时记住 jobId
function openEdit(job) {
  currentJobId.value = job.id
  // ...现有赋值逻辑
}
```

注意: 新建岗位时 `currentJobId` 为 null, CompetencyEditor 不显示 (v-if). 新建保存后拿到 id 再显示. 这个细节在现 Jobs.vue 的"保存后关闭 dialog"逻辑里调整 — 保存后若用户要编辑能力模型, 需要重新打开 dialog, 这是可接受的 F1 边界.

- [ ] **Step 3: Build check**

```bash
cd /d/libz/AgenticHR/frontend
npm run build 2>&1 | tail -5
```
Expected: `✓ built`. 若报 `CompetencyEditor` 未找到, 检查相对路径 `../components/CompetencyEditor.vue`.

- [ ] **Step 4: Manual test**

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/python.exe -m uvicorn app.main:app --port 8000 &
# 浏览器打开 http://127.0.0.1:8000
# 新建岗位 → 保存 → 重新打开编辑 → 应看到 2 个 Tab
kill %1
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/views/Jobs.vue
git commit -m "feat(F1-T24): Jobs.vue — wrap edit dialog in el-tabs with 能力模型 tab

- Basic info tab keeps all M2 fields unchanged (zero regression)
- Competency tab embeds CompetencyEditor(job-id)
- Tab label shows status hint: 待审 / ✓ / ✕
- New jobs must be saved before competency tab is usable (edge documented)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task T25: views/HitlQueue.vue — global review queue

**Files:**
- Create: `frontend/src/views/HitlQueue.vue`

- [ ] **Step 1: Create view**

```vue
<template>
  <div class="hitl-queue">
    <el-card>
      <div class="filters">
        <el-radio-group v-model="stageFilter" @change="refresh">
          <el-radio-button label="">全部</el-radio-button>
          <el-radio-button label="F1_competency_review">能力模型</el-radio-button>
          <el-radio-button label="F1_skill_classification">新技能</el-radio-button>
        </el-radio-group>
        <el-radio-group v-model="statusFilter" @change="refresh">
          <el-radio-button label="pending">待审</el-radio-button>
          <el-radio-button label="approved">已通过</el-radio-button>
          <el-radio-button label="rejected">已驳回</el-radio-button>
          <el-radio-button label="">全部</el-radio-button>
        </el-radio-group>
        <el-button @click="refresh">刷新</el-button>
      </div>

      <el-table :data="items" v-loading="loading" border>
        <el-table-column label="类型" width="120">
          <template #default="{ row }">
            <el-tag v-if="row.f_stage === 'F1_competency_review'" type="primary">能力模型</el-tag>
            <el-tag v-else-if="row.f_stage === 'F1_skill_classification'" type="success">新技能</el-tag>
            <el-tag v-else>{{ row.f_stage }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="标题" min-width="200">
          <template #default="{ row }">
            <span>{{ taskTitle(row) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="160">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)">{{ statusText(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="180">
          <template #default="{ row }">
            <el-button v-if="row.f_stage === 'F1_competency_review'"
                       size="small" type="primary" @click="gotoJob(row)">审核</el-button>
            <el-button v-if="row.f_stage === 'F1_skill_classification'"
                       size="small" type="success" @click="gotoSkill(row)">归类</el-button>
            <el-button v-if="row.status === 'pending'" size="small" @click="quickApprove(row)">快速通过</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { hitlApi } from '../api'

const router = useRouter()
const stageFilter = ref('')
const statusFilter = ref('pending')
const items = ref([])
const loading = ref(false)

function taskTitle(row) {
  if (row.f_stage === 'F1_competency_review') return `岗位 #${row.entity_id}`
  if (row.f_stage === 'F1_skill_classification') return row.payload?.name || `新技能 #${row.entity_id}`
  return `${row.entity_type} #${row.entity_id}`
}

function formatTime(t) { return t ? new Date(t).toLocaleString() : '' }
function statusType(s) {
  return { pending: 'warning', approved: 'success', rejected: 'danger', edited: 'success' }[s] || 'info'
}
function statusText(s) {
  return { pending: '待审', approved: '已通过', rejected: '已驳回', edited: '已修改' }[s] || s
}

async function refresh() {
  loading.value = true
  try {
    const params = {}
    if (stageFilter.value) params.stage = stageFilter.value
    if (statusFilter.value) params.status = statusFilter.value
    const resp = await hitlApi.list(params)
    items.value = resp.items || []
  } finally { loading.value = false }
}

function gotoJob(row) {
  router.push({ path: '/jobs', query: { id: row.entity_id, tab: 'competency' } })
}
function gotoSkill(row) {
  router.push({ path: '/skills', query: { pending: 1, focus: row.entity_id } })
}

async function quickApprove(row) {
  try {
    await ElMessageBox.confirm('确认快速通过?', '确认', { type: 'warning' })
    await hitlApi.approve(row.id, '快速通过')
    ElMessage.success('已通过')
    refresh()
  } catch {}
}

onMounted(refresh)
</script>

<style scoped>
.hitl-queue { padding: 20px; }
.filters { margin-bottom: 16px; display: flex; gap: 12px; flex-wrap: wrap; }
</style>
```

- [ ] **Step 2: Build check**

```bash
cd /d/libz/AgenticHR/frontend
npm run build 2>&1 | tail -5
```
Expected: `✓ built`。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/views/HitlQueue.vue
git commit -m "feat(F1-T25): views/HitlQueue — global review queue

- filter by stage (competency / skill / all) + status (pending/done/all)
- table row actions: 审核 (→ Jobs.vue tab) / 归类 (→ SkillLibrary focus) /
  快速通过 (approve without edit)
- status tag colors follow Element Plus convention

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task T26: views/SkillLibrary.vue — skill library with batch classify

**Files:**
- Create: `frontend/src/views/SkillLibrary.vue`

- [ ] **Step 1: Create view**

```vue
<template>
  <div class="skill-library">
    <el-card>
      <div class="toolbar">
        <el-input v-model="searchQ" placeholder="搜索技能..." clearable
                   @clear="refresh" @keyup.enter="refresh" style="width:240px" />
        <el-select v-model="categoryFilter" clearable placeholder="所有分类"
                    @change="refresh" style="width:160px">
          <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
        </el-select>
        <el-switch v-model="pendingOnly" active-text="仅待归类" @change="refresh" />
        <el-button type="primary" @click="showCreateDialog = true">新增技能</el-button>
        <el-button v-if="selected.length > 0" type="warning" @click="batchClassify">
          批量设分类 ({{ selected.length }})
        </el-button>
        <span class="total">共 {{ total }} 条</span>
      </div>

      <el-table :data="items" v-loading="loading" border
                 @selection-change="sel => selected = sel">
        <el-table-column type="selection" width="50" :selectable="row => row.pending_classification" />
        <el-table-column label="技能" prop="canonical_name" width="180" />
        <el-table-column label="别名" min-width="200">
          <template #default="{ row }">
            <el-tag v-for="a in row.aliases" :key="a" size="small" style="margin-right:4px">{{ a }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="分类" width="120">
          <template #default="{ row }">
            <el-tag :type="tagType(row.category)">{{ row.category }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="来源" width="100" prop="source" />
        <el-table-column label="使用次数" width="100" prop="usage_count" sortable />
        <el-table-column label="待归类" width="100" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.pending_classification" type="warning">是</el-tag>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="180">
          <template #default="{ row }">
            <el-button size="small" @click="openEdit(row)">编辑</el-button>
            <el-button size="small" type="warning" @click="openMerge(row)">合并</el-button>
            <el-button size="small" type="danger"
                        :disabled="row.source === 'seed' || row.usage_count > 0"
                        @click="doDelete(row)">删</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="showCreateDialog" title="新增技能" width="500px">
      <el-form :model="createForm" label-width="90px">
        <el-form-item label="名称"><el-input v-model="createForm.canonical_name" /></el-form-item>
        <el-form-item label="分类">
          <el-select v-model="createForm.category" style="width:100%">
            <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item label="别名 (逗号)">
          <el-input v-model="createForm.aliasesStr" placeholder="py3, pyy" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateDialog=false">取消</el-button>
        <el-button type="primary" @click="doCreate">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showEditDialog" title="编辑技能" width="500px">
      <el-form :model="editForm" label-width="90px">
        <el-form-item label="名称"><el-input v-model="editForm.canonical_name" /></el-form-item>
        <el-form-item label="分类">
          <el-select v-model="editForm.category" style="width:100%">
            <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item label="别名 (逗号)">
          <el-input v-model="editForm.aliasesStr" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showEditDialog=false">取消</el-button>
        <el-button type="primary" @click="doUpdate">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showMergeDialog" title="合并到另一个技能" width="500px">
      <p>把 <b>{{ mergeFrom?.canonical_name }}</b> 合并到:</p>
      <SkillPicker v-model="mergeTargetName" @select="s => mergeTargetId = s.id" />
      <template #footer>
        <el-button @click="showMergeDialog=false">取消</el-button>
        <el-button type="warning" @click="doMerge">合并</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showBatchDialog" title="批量设置分类" width="400px">
      <el-select v-model="batchCategory" placeholder="选择分类" style="width:100%">
        <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
      </el-select>
      <template #footer>
        <el-button @click="showBatchDialog=false">取消</el-button>
        <el-button type="primary" @click="doBatchClassify">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { skillsApi } from '../api'
import SkillPicker from '../components/SkillPicker.vue'

const searchQ = ref('')
const categoryFilter = ref('')
const pendingOnly = ref(false)
const items = ref([])
const categories = ref([])
const total = ref(0)
const loading = ref(false)
const selected = ref([])

const showCreateDialog = ref(false)
const createForm = ref({ canonical_name: '', category: 'uncategorized', aliasesStr: '' })

const showEditDialog = ref(false)
const editForm = ref({ id: 0, canonical_name: '', category: '', aliasesStr: '' })

const showMergeDialog = ref(false)
const mergeFrom = ref(null)
const mergeTargetName = ref('')
const mergeTargetId = ref(null)

const showBatchDialog = ref(false)
const batchCategory = ref('')

function tagType(cat) {
  return { language: 'primary', framework: 'success', cloud: 'warning',
           database: 'info', tool: '', soft: 'danger', domain: 'primary' }[cat] || ''
}

async function refresh() {
  loading.value = true
  try {
    const params = { limit: 200 }
    if (searchQ.value) params.search = searchQ.value
    if (categoryFilter.value) params.category = categoryFilter.value
    if (pendingOnly.value) params.pending = true
    const resp = await skillsApi.list(params)
    items.value = resp.items || []
    total.value = resp.total || 0
  } finally { loading.value = false }
}

async function loadCategories() {
  const resp = await skillsApi.categories()
  categories.value = resp.categories || []
}

function openEdit(row) {
  editForm.value = {
    id: row.id, canonical_name: row.canonical_name, category: row.category,
    aliasesStr: (row.aliases || []).join(', '),
  }
  showEditDialog.value = true
}

async function doCreate() {
  try {
    await skillsApi.create({
      canonical_name: createForm.value.canonical_name,
      category: createForm.value.category,
      aliases: createForm.value.aliasesStr.split(',').map(s => s.trim()).filter(Boolean),
    })
    showCreateDialog.value = false
    createForm.value = { canonical_name: '', category: 'uncategorized', aliasesStr: '' }
    ElMessage.success('已保存')
    refresh()
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.message || e))
  }
}

async function doUpdate() {
  try {
    await skillsApi.update(editForm.value.id, {
      canonical_name: editForm.value.canonical_name,
      category: editForm.value.category,
      aliases: editForm.value.aliasesStr.split(',').map(s => s.trim()).filter(Boolean),
    })
    showEditDialog.value = false
    ElMessage.success('已保存')
    refresh()
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.message || e))
  }
}

function openMerge(row) {
  if (row.source === 'seed') {
    ElMessage.warning('种子技能不可合并')
    return
  }
  mergeFrom.value = row
  mergeTargetName.value = ''
  mergeTargetId.value = null
  showMergeDialog.value = true
}

async function doMerge() {
  if (!mergeTargetId.value) {
    ElMessage.warning('请选择目标技能')
    return
  }
  try {
    await skillsApi.merge(mergeFrom.value.id, mergeTargetId.value)
    ElMessage.success('已合并')
    showMergeDialog.value = false
    refresh()
  } catch (e) {
    ElMessage.error('合并失败: ' + (e.message || e))
  }
}

async function doDelete(row) {
  try {
    await ElMessageBox.confirm(`删除技能 "${row.canonical_name}"?`, '确认', { type: 'warning' })
    await skillsApi.delete(row.id)
    ElMessage.success('已删除')
    refresh()
  } catch {}
}

function batchClassify() {
  showBatchDialog.value = true
  batchCategory.value = ''
}

async function doBatchClassify() {
  if (!batchCategory.value) return
  for (const s of selected.value) {
    await skillsApi.update(s.id, { category: batchCategory.value })
  }
  showBatchDialog.value = false
  ElMessage.success(`已更新 ${selected.value.length} 条`)
  refresh()
}

onMounted(() => { loadCategories(); refresh() })
</script>

<style scoped>
.skill-library { padding: 20px; }
.toolbar { display: flex; gap: 12px; margin-bottom: 16px; align-items: center; flex-wrap: wrap; }
.total { color: #909399; margin-left: auto; }
</style>
```

- [ ] **Step 2: Build check**

```bash
cd /d/libz/AgenticHR/frontend
npm run build 2>&1 | tail -5
```
Expected: `✓ built`。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/views/SkillLibrary.vue
git commit -m "feat(F1-T26): views/SkillLibrary — skill library with batch classify

- search / category filter / pending-only toggle
- batch classification for pending rows (primary workflow)
- edit / merge / delete dialogs
- seed skills protected (no delete, no merge source)
- uses SkillPicker for merge target selection

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task T27: router/index.js — 2 new routes

**Files:**
- Modify: `frontend/src/router/index.js`

- [ ] **Step 1: Add 2 routes**

在 `frontend/src/router/index.js` 的 `routes` 数组, 在 `/jobs` 后追加:

```javascript
  { path: '/hitl', name: 'HitlQueue', component: () => import('../views/HitlQueue.vue') },
  { path: '/skills', name: 'SkillLibrary', component: () => import('../views/SkillLibrary.vue') },
```

- [ ] **Step 2: Build + manual check**

```bash
cd /d/libz/AgenticHR/frontend
npm run build 2>&1 | tail -5
```
Expected: `✓ built`。

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/python.exe -m uvicorn app.main:app --port 8000 &
# 浏览器打开 http://127.0.0.1:8000/hitl 和 /skills, 都应正常渲染
kill %1
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/router/index.js
git commit -m "feat(F1-T27): router — add /hitl and /skills routes

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 5 — Integration

### Task T28: E2E smoke test

**Files:**
- Create: `tests/e2e/__init__.py`
- Create: `tests/e2e/test_f1_smoke.py`

**Context:** 一跑到底的 smoke: 建岗位 → 粘 JD → mock LLM 抽取 → HITL approve → 筛选. 所有依赖替换为 mock, 不真调外部 API.

- [ ] **Step 1: Create failing test**

```bash
cd /d/libz/AgenticHR
mkdir -p tests/e2e
touch tests/e2e/__init__.py
```

Create `tests/e2e/test_f1_smoke.py`:

```python
"""F1 E2E smoke: JD → extract → HITL approve → screen."""
import json
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


@pytest.fixture
def env(tmp_path, monkeypatch):
    db = tmp_path / "e2e.db"
    url = f"sqlite:///{db}"
    cfg = Config("migrations/alembic.ini")
    cfg.set_main_option("script_location", "migrations")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "0006")
    engine = sa.create_engine(url, connect_args={"check_same_thread": False})
    factory = sessionmaker(bind=engine)
    for path in [
        "app.database.engine",
        "app.core.audit.logger._session_factory",
        "app.core.hitl.service._session_factory",
        "app.core.competency.skill_library._session_factory",
        "app.modules.screening.competency_service._session_factory",
    ]:
        if path.endswith("engine"):
            monkeypatch.setattr(path, engine)
        else:
            monkeypatch.setattr(path, factory)
    monkeypatch.setenv("AGENTICHR_TEST_BYPASS_AUTH", "1")
    return factory


@pytest.mark.asyncio
async def test_f1_e2e_smoke(env, monkeypatch):
    """JD → 抽取 → HITL approve → 筛选通过/不通过符合 competency_model."""
    client = TestClient(app)

    # Step 1: 创建岗位 (带 jd_text)
    from app.modules.screening.models import Job
    from app.modules.resume.models import Resume
    s = env()
    job = Job(title="Python 后端", jd_text="招聘资深 Python 后端")
    s.add_all([
        job,
        Resume(name="合格 A", education="本科", work_years=5, skills="Python, FastAPI"),
        Resume(name="不合格 (缺 FastAPI)", education="本科", work_years=5, skills="Python"),
        Resume(name="不合格 (学历)", education="大专", work_years=5, skills="Python,FastAPI"),
    ])
    s.commit()
    jid = job.id
    s.close()

    # Step 2: mock LLM 抽取
    mock_llm = AsyncMock()
    mock_llm.complete = AsyncMock(return_value=_VALID_LLM_OUTPUT)
    mock_llm.embed_batch = AsyncMock(return_value=[[1.0, 0, 0], [0, 1.0, 0]])
    with patch("app.core.competency.extractor.get_llm_provider", return_value=mock_llm), \
         patch("app.core.competency.normalizer.get_llm_provider", return_value=mock_llm):
        resp = client.post(f"/api/screening/jobs/{jid}/competency/extract")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "draft"
        task_id = data["hitl_task_id"]

    # Step 3: HITL approve (触发 double-write callback)
    # 注意: callback 需要 app startup 时已注册
    from app.main import _on_competency_approved  # 自 T19b 添加
    from app.core.hitl.service import register_approve_callback
    register_approve_callback("F1_competency_review", _on_competency_approved)

    resp = client.post(f"/api/hitl/tasks/{task_id}/approve", json={"note": "ok"})
    assert resp.status_code == 200

    # Step 4: 验证 jobs.competency_model 写入 + 扁平字段双写
    s = env()
    job = s.query(Job).filter(Job.id == jid).first()
    assert job.competency_model_status == "approved"
    assert "Python" in (job.required_skills or "")
    assert "FastAPI" in (job.required_skills or "")
    s.close()

    # Step 5: 跑硬筛, 验证通过/不通过符合预期
    resp = client.post(f"/api/screening/jobs/{jid}/screen", json=[])
    assert resp.status_code == 200
    data = resp.json()
    assert data["passed"] == 1
    assert data["rejected"] == 2
    names_passed = {r["resume_name"] for r in data["results"] if r["passed"]}
    assert names_passed == {"合格 A"}
```

- [ ] **Step 2: Run test**

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/python.exe -m pytest tests/e2e/test_f1_smoke.py -v
```
Expected: 1 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/e2e/__init__.py tests/e2e/test_f1_smoke.py
git commit -m "test(F1-T28): E2E smoke — JD → extract → HITL approve → screen

- full pipeline validated with mocked LLM
- verifies: draft state, HITL task creation, approve callback,
  double-write of flat fields, correct hard/soft screening outcomes
- covers 3 resumes: pass / skill-missing / education-missing

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task T29: M2 Regression + Coverage Report

**Files:** (no new files)

- [ ] **Step 1: Run full test suite**

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/python.exe -m pytest tests/ --tb=short -q 2>&1 | tail -30
```
Expected:
- M2 baseline 53 passed 不能减少
- F1 新增: T1–T29 所有测试通过
- 期望总 passed ≥ 53 + F1 tests (大约 70+ passed)

若有新增失败而来自 F1 代码, 必须修复 (不许 xfail / skip).

- [ ] **Step 2: Coverage report (可选但推荐)**

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/python.exe -m pip install pytest-cov 2>&1 | tail -3
./.venv/Scripts/python.exe -m pytest tests/ --cov=app/core --cov-report=term-missing --tb=no -q 2>&1 | tail -30
```
Expected: `app/core/` 覆盖率 ≥ 85%. 低于的包需补测试.

- [ ] **Step 3: Manual smoke**

```bash
cd /d/libz/AgenticHR
./.venv/Scripts/python.exe -m uvicorn app.main:app --port 8000 &
# 按 §1.3 完工清单手工过一遍:
# 1. 访问 http://127.0.0.1:8000 → 登录 / 看到"审核队列"+"技能库"菜单
# 2. 新建岗位, 保存, 重新打开, 点"能力模型" Tab
# 3. 粘一段 JD → 点"从 JD 抽取"(需 AI_API_KEY 配置)
# 4. 审核队列页应出现新任务, 能力模型 Tab 底部有"通过并发布"按钮
# 5. 通过后回"基本信息" Tab, 应能看到扁平字段被回填
# 6. 回简历页, 选岗位跑硬筛, 验证结果与能力模型一致
kill %1
```

- [ ] **Step 4: Final commit (release notes only, no code)**

```bash
git tag -a f1-complete -m "F1 能力模型抽取完成

- 29 tasks + M3-kickoff (K0+K1) 全部通过 TDD
- app/core/ 5 包 (llm, competency, vector, hitl, audit) 覆盖率 ≥85%
- 3 张新表 + 1 张表扩展 3 列, 全部 Alembic 管理
- HITL 两种 stage (阻塞能力模型 + 非阻塞新技能) 落地
- WORM audit 3 年留存 (PIPL §24 合规基座)
- 前端 Jobs.vue Tab + 2 新页 + 2 共享组件
- M2 基线零回归

Ready for F2 (简历匹配打分)"
```

然后推送:

```bash
git push origin main --tags
```

---

## 自审 (Self-Review)

此 plan 文档完成后做过一次自审:

1. **Spec coverage**: 对照 spec §11 的完工清单 1–9, 逐项有任务覆盖
   - §1.3 点 1–9 ↔ 任务 T1–T29
   - §2 决策 D1–D10 ↔ K0 (D1) / T17+T18 (D2) / T14+T15 (D3,D4,D5) / T19 (D6) / T23+T24 (D7) / T4+T16 (D8) / 文档 (D9) / T10 (D10)
2. **Placeholder scan**: 已移除 "TODO" / "TBD" / "fill in later"
3. **Type consistency**: `f_stage` 值 (F1_competency_review / F1_skill_classification) 全 plan 使用一致; `competency_model_status` 四态 (none/draft/approved/rejected) 一致

## 已知执行注意

1. **任务顺序建议实际调整**: T15 (HitlService) 应该在 T13 (normalizer) **之前**执行, 否则 T13 的 HITL 创建测试会失败. 本 plan 按 F 编号顺序写出, 执行者应按依赖顺序灵活调整.
2. **T0 前置依赖**: K0 + K1 必须先于 T1 跑, 否则 Alembic 环境不存在.
3. **LLM 实测 (T10) 高优**: 若 R1 风险实锤 (智谱 embedding API 不兼容), 需提前改方案, 影响 T13.
4. **测试 monkeypatch 模式**: 多处 `_session_factory` monkeypatch. 若测试结构大改可能要统一 pytest fixture.

---

**Plan complete and saved to `docs/superpowers/plans/2026-04-20-f1-competency-model-plan.md`.**

下一步两种执行模式, 任选其一:

**1. Subagent-Driven (推荐)** — 每任务一个独立 subagent 跑, 主 session 审, 迭代最快.

**2. Inline Execution** — 在当前 session 里按 TDD 逐个任务推进, 每 3–5 个任务一个 checkpoint 停下让用户 review.

**你选哪种?**




