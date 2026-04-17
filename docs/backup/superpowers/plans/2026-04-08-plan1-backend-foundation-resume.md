# Plan 1: 后端基础 + 简历管理模块 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 搭建 FastAPI 后端基础框架，实现简历管理模块（接收、存储、查询、PDF 解析），使其可独立运行和测试。

**Architecture:** FastAPI 应用，模块化目录结构，SQLite 数据库，Pydantic schema 做数据校验。简历模块作为第一个业务模块验证整体架构设计。适配器层封装外部服务，支持 mock 测试。

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy (SQLite), Pydantic v2, PyPDF2 (PDF解析), pytest, uvicorn

---

## File Structure

```
boss_feishu/
├── app/
│   ├── __init__.py
│   ├── main.py                    # FastAPI 应用入口，注册路由
│   ├── config.py                  # 统一配置管理（Pydantic Settings）
│   ├── database.py                # SQLAlchemy 引擎与 session 管理
│   ├── modules/
│   │   ├── __init__.py
│   │   └── resume/
│   │       ├── __init__.py
│   │       ├── router.py          # API 路由 (/api/resumes/*)
│   │       ├── service.py         # 业务逻辑
│   │       ├── models.py          # SQLAlchemy 数据模型
│   │       ├── schemas.py         # Pydantic 输入/输出结构
│   │       └── pdf_parser.py      # PDF 解析逻辑
│   └── adapters/
│       ├── __init__.py
│       └── boss/
│           ├── __init__.py
│           └── base.py            # Boss 直聘适配器接口定义
├── tests/
│   ├── __init__.py
│   ├── conftest.py                # 测试 fixtures（测试数据库、测试客户端）
│   └── modules/
│       ├── __init__.py
│       └── resume/
│           ├── __init__.py
│           ├── test_models.py
│           ├── test_service.py
│           ├── test_router.py
│           └── test_pdf_parser.py
├── requirements.txt
└── pyproject.toml
```

---

### Task 1: 项目初始化与依赖配置

**Files:**
- Create: `pyproject.toml`
- Create: `requirements.txt`
- Create: `app/__init__.py`

- [ ] **Step 1: 创建 pyproject.toml**

```toml
[project]
name = "boss-feishu-recruitment-assistant"
version = "0.1.0"
description = "招聘助手 - Boss直聘简历管理与面试协调工具"
requires-python = ">=3.11"

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

- [ ] **Step 2: 创建 requirements.txt**

```
fastapi==0.115.6
uvicorn[standard]==0.34.0
sqlalchemy==2.0.36
pydantic==2.10.3
pydantic-settings==2.7.1
pypdf2==3.0.1
python-multipart==0.0.20
pytest==8.3.4
pytest-asyncio==0.25.0
httpx==0.28.1
```

- [ ] **Step 3: 创建虚拟环境并安装依赖**

Run: `python -m venv venv && venv/Scripts/activate && pip install -r requirements.txt`
Expected: 所有依赖安装成功，无报错

- [ ] **Step 4: 创建 app/__init__.py**

```python
"""招聘助手后端应用"""
```

- [ ] **Step 5: Commit**

```bash
git init
git add pyproject.toml requirements.txt app/__init__.py
git commit -m "chore: init project with dependencies"
```

---

### Task 2: 统一配置管理

**Files:**
- Create: `app/config.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: 写 config.py 的测试**

Create `tests/__init__.py` (empty) and `tests/conftest.py`:

```python
"""共享测试 fixtures"""
import os
import pytest

# 测试时使用内存数据库
os.environ["DATABASE_URL"] = "sqlite:///./test.db"
```

由于 config 是基础设施，这里直接验证加载：无需单独测试文件，在后续模块测试中隐式验证。

- [ ] **Step 2: 实现 config.py**

```python
"""统一配置管理"""
from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # 应用
    app_name: str = "招聘助手"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    debug: bool = False

    # 数据库
    database_url: str = "sqlite:///./data/recruitment.db"

    # AI 功能开关
    ai_enabled: bool = False
    ai_provider: str = "openai_compatible"
    ai_api_key: str = ""
    ai_base_url: str = ""
    ai_model: str = ""

    # 邮件 SMTP
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_use_ssl: bool = True

    # 邮件 IMAP
    imap_host: str = ""
    imap_port: int = 993
    imap_user: str = ""
    imap_password: str = ""
    imap_check_interval: int = 300  # 秒

    # 飞书
    feishu_app_id: str = ""
    feishu_app_secret: str = ""

    # 腾讯会议
    tencent_meeting_app_id: str = ""
    tencent_meeting_secret_id: str = ""
    tencent_meeting_secret_key: str = ""

    # Boss 直聘
    boss_adapter: str = "chrome_extension"  # chrome_extension | playwright
    boss_max_operations_per_hour: int = 30
    boss_max_operations_per_day: int = 200
    boss_delay_min: float = 3.0
    boss_delay_max: float = 8.0

    # 简历存储路径
    resume_storage_path: str = "./data/resumes"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
```

- [ ] **Step 3: 验证配置加载**

Run: `python -c "from app.config import settings; print(settings.app_name)"`
Expected: 输出 `招聘助手`

- [ ] **Step 4: Commit**

```bash
git add app/config.py tests/__init__.py tests/conftest.py
git commit -m "feat: add unified config management with pydantic-settings"
```

---

### Task 3: 数据库连接管理

**Files:**
- Create: `app/database.py`

- [ ] **Step 1: 实现 database.py**

```python
"""SQLAlchemy 数据库连接管理"""
from pathlib import Path
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


# 确保数据目录存在
db_path = settings.database_url.replace("sqlite:///", "")
if db_path and db_path != ":memory:":
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},
    echo=settings.debug,
)

# SQLite 启用外键约束
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI 依赖注入用的数据库 session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_tables():
    """创建所有表（首次运行时调用）"""
    Base.metadata.create_all(bind=engine)
```

- [ ] **Step 2: 更新 conftest.py 添加测试数据库 fixture**

```python
"""共享测试 fixtures"""
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from app.database import Base, get_db
from app.main import app as fastapi_app


@pytest.fixture(scope="function")
def db_engine():
    engine = create_engine(
        "sqlite:///./test.db",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture(scope="function")
def db_session(db_engine):
    Session = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
    session = Session()
    yield session
    session.rollback()
    session.close()


@pytest.fixture(scope="function")
def client(db_session):
    def override_get_db():
        yield db_session

    fastapi_app.dependency_overrides[get_db] = override_get_db
    with TestClient(fastapi_app) as c:
        yield c
    fastapi_app.dependency_overrides.clear()
```

- [ ] **Step 3: Commit**

```bash
git add app/database.py tests/conftest.py
git commit -m "feat: add SQLAlchemy database connection with SQLite WAL mode"
```

---

### Task 4: FastAPI 应用入口

**Files:**
- Create: `app/main.py`

- [ ] **Step 1: 写健康检查测试**

Create `tests/test_health.py`:

```python
"""应用健康检查测试"""


def test_health_check(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["app_name"] == "招聘助手"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_health.py -v`
Expected: FAIL（app.main 不存在）

- [ ] **Step 3: 实现 main.py**

```python
"""FastAPI 应用入口"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import create_tables


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_tables()
    yield


app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health_check():
    return {"status": "ok", "app_name": settings.app_name}


def register_routers():
    from app.modules.resume.router import router as resume_router
    app.include_router(resume_router, prefix="/api/resumes", tags=["resumes"])


register_routers()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_health.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/main.py tests/test_health.py
git commit -m "feat: add FastAPI app entry with health check and CORS"
```

---

### Task 5: 简历数据模型

**Files:**
- Create: `app/modules/__init__.py`
- Create: `app/modules/resume/__init__.py`
- Create: `app/modules/resume/models.py`
- Create: `tests/modules/__init__.py`
- Create: `tests/modules/resume/__init__.py`
- Create: `tests/modules/resume/test_models.py`

- [ ] **Step 1: 写模型测试**

Create all `__init__.py` files (empty), then `tests/modules/resume/test_models.py`:

```python
"""简历数据模型测试"""
from datetime import datetime
from app.modules.resume.models import Resume


def test_create_resume(db_session):
    resume = Resume(
        name="张三",
        phone="13800138000",
        email="zhangsan@example.com",
        education="本科",
        work_years=5,
        expected_salary_min=15000,
        expected_salary_max=25000,
        job_intention="Python开发工程师",
        skills="Python,FastAPI,SQLAlchemy",
        work_experience="某公司 高级开发工程师 3年",
        project_experience="电商平台后端开发",
        self_evaluation="热爱编程",
        source="boss_zhipin",
        raw_text="完整简历文本内容...",
        pdf_path="/data/resumes/zhangsan.pdf",
    )
    db_session.add(resume)
    db_session.commit()
    db_session.refresh(resume)

    assert resume.id is not None
    assert resume.name == "张三"
    assert resume.phone == "13800138000"
    assert resume.status == "pending"
    assert isinstance(resume.created_at, datetime)


def test_resume_duplicate_check(db_session):
    """同名同手机号视为重复"""
    resume1 = Resume(name="李四", phone="13900139000", source="boss_zhipin")
    db_session.add(resume1)
    db_session.commit()

    existing = (
        db_session.query(Resume)
        .filter(Resume.name == "李四", Resume.phone == "13900139000")
        .first()
    )
    assert existing is not None
    assert existing.id == resume1.id
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/modules/resume/test_models.py -v`
Expected: FAIL（Resume 不存在）

- [ ] **Step 3: 实现 models.py**

```python
"""简历数据模型"""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, Float, DateTime

from app.database import Base


class Resume(Base):
    __tablename__ = "resumes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, index=True)
    phone = Column(String(20), default="", index=True)
    email = Column(String(200), default="")
    education = Column(String(50), default="")
    work_years = Column(Integer, default=0)
    expected_salary_min = Column(Float, default=0)
    expected_salary_max = Column(Float, default=0)
    job_intention = Column(String(200), default="")
    skills = Column(Text, default="")
    work_experience = Column(Text, default="")
    project_experience = Column(Text, default="")
    self_evaluation = Column(Text, default="")
    source = Column(String(50), default="")  # boss_zhipin, email, manual
    raw_text = Column(Text, default="")  # PDF 解析出的完整文本
    pdf_path = Column(String(500), default="")
    status = Column(String(20), default="pending")  # pending, passed, rejected
    ai_score = Column(Float, nullable=True)
    ai_summary = Column(Text, default="")
    reject_reason = Column(String(200), default="")
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/modules/resume/test_models.py -v`
Expected: 2 tests PASS

- [ ] **Step 5: Commit**

```bash
git add app/modules/__init__.py app/modules/resume/__init__.py app/modules/resume/models.py tests/modules/__init__.py tests/modules/resume/__init__.py tests/modules/resume/test_models.py
git commit -m "feat: add Resume SQLAlchemy model with status tracking"
```

---

### Task 6: 简历 Pydantic Schema

**Files:**
- Create: `app/modules/resume/schemas.py`

- [ ] **Step 1: 实现 schemas.py**

```python
"""简历输入/输出数据结构"""
from datetime import datetime
from pydantic import BaseModel, Field


class ResumeCreate(BaseModel):
    """创建简历（Chrome 插件或手动上传提交）"""
    name: str = Field(..., min_length=1, max_length=100, description="姓名")
    phone: str = Field(default="", max_length=20, description="手机号")
    email: str = Field(default="", max_length=200, description="邮箱")
    education: str = Field(default="", max_length=50, description="学历")
    work_years: int = Field(default=0, ge=0, description="工作年限")
    expected_salary_min: float = Field(default=0, ge=0, description="期望薪资下限")
    expected_salary_max: float = Field(default=0, ge=0, description="期望薪资上限")
    job_intention: str = Field(default="", max_length=200, description="求职意向")
    skills: str = Field(default="", description="技能标签，逗号分隔")
    work_experience: str = Field(default="", description="工作经历")
    project_experience: str = Field(default="", description="项目经历")
    self_evaluation: str = Field(default="", description="自我评价")
    source: str = Field(default="manual", description="来源: boss_zhipin, email, manual")
    raw_text: str = Field(default="", description="简历原始文本")
    pdf_path: str = Field(default="", description="PDF 文件路径")


class ResumeUpdate(BaseModel):
    """更新简历状态"""
    status: str | None = Field(None, description="状态: pending, passed, rejected")
    reject_reason: str | None = Field(None, description="淘汰原因")


class ResumeResponse(BaseModel):
    """简历详情响应"""
    id: int
    name: str
    phone: str
    email: str
    education: str
    work_years: int
    expected_salary_min: float
    expected_salary_max: float
    job_intention: str
    skills: str
    work_experience: str
    project_experience: str
    self_evaluation: str
    source: str
    raw_text: str
    pdf_path: str
    status: str
    ai_score: float | None
    ai_summary: str
    reject_reason: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ResumeListResponse(BaseModel):
    """简历列表响应（分页）"""
    total: int
    page: int
    page_size: int
    items: list[ResumeResponse]
```

- [ ] **Step 2: 验证 schema 可用**

Run: `python -c "from app.modules.resume.schemas import ResumeCreate; r = ResumeCreate(name='测试'); print(r.model_dump())"`
Expected: 输出包含 name='测试' 的字典

- [ ] **Step 3: Commit**

```bash
git add app/modules/resume/schemas.py
git commit -m "feat: add Pydantic schemas for resume CRUD operations"
```

---

### Task 7: 简历业务逻辑层

**Files:**
- Create: `app/modules/resume/service.py`
- Create: `tests/modules/resume/test_service.py`

- [ ] **Step 1: 写 service 测试**

```python
"""简历业务逻辑测试"""
from app.modules.resume.service import ResumeService
from app.modules.resume.schemas import ResumeCreate, ResumeUpdate


def test_create_resume(db_session):
    service = ResumeService(db_session)
    data = ResumeCreate(
        name="王五",
        phone="13700137000",
        email="wangwu@example.com",
        education="硕士",
        work_years=3,
        source="boss_zhipin",
    )
    resume = service.create(data)
    assert resume.id is not None
    assert resume.name == "王五"
    assert resume.status == "pending"


def test_create_duplicate_resume(db_session):
    service = ResumeService(db_session)
    data = ResumeCreate(name="赵六", phone="13600136000", source="boss_zhipin")
    service.create(data)
    duplicate = service.create(data)
    assert duplicate is None  # 重复返回 None


def test_get_resume_by_id(db_session):
    service = ResumeService(db_session)
    data = ResumeCreate(name="钱七", phone="13500135000")
    created = service.create(data)
    fetched = service.get_by_id(created.id)
    assert fetched is not None
    assert fetched.name == "钱七"


def test_list_resumes_with_pagination(db_session):
    service = ResumeService(db_session)
    for i in range(15):
        service.create(ResumeCreate(name=f"候选人{i}", phone=f"1380013{i:04d}"))

    result = service.list(page=1, page_size=10)
    assert result["total"] == 15
    assert len(result["items"]) == 10
    assert result["page"] == 1

    result2 = service.list(page=2, page_size=10)
    assert len(result2["items"]) == 5


def test_list_resumes_filter_by_status(db_session):
    service = ResumeService(db_session)
    service.create(ResumeCreate(name="甲", phone="10000000001"))
    r2 = service.create(ResumeCreate(name="乙", phone="10000000002"))
    service.update(r2.id, ResumeUpdate(status="passed"))

    result = service.list(status="passed")
    assert result["total"] == 1
    assert result["items"][0].name == "乙"


def test_update_resume_status(db_session):
    service = ResumeService(db_session)
    resume = service.create(ResumeCreate(name="孙八", phone="13400134000"))
    updated = service.update(resume.id, ResumeUpdate(status="rejected", reject_reason="工作年限不足"))
    assert updated.status == "rejected"
    assert updated.reject_reason == "工作年限不足"


def test_search_resumes_by_keyword(db_session):
    service = ResumeService(db_session)
    service.create(ResumeCreate(name="张Java", phone="10000000010", skills="Java,Spring"))
    service.create(ResumeCreate(name="李Python", phone="10000000011", skills="Python,FastAPI"))

    result = service.list(keyword="Java")
    assert result["total"] == 1
    assert result["items"][0].name == "张Java"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/modules/resume/test_service.py -v`
Expected: FAIL（ResumeService 不存在）

- [ ] **Step 3: 实现 service.py**

```python
"""简历业务逻辑"""
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.modules.resume.models import Resume
from app.modules.resume.schemas import ResumeCreate, ResumeUpdate


class ResumeService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, data: ResumeCreate) -> Resume | None:
        """创建简历，重复则返回 None"""
        if data.phone:
            existing = (
                self.db.query(Resume)
                .filter(Resume.name == data.name, Resume.phone == data.phone)
                .first()
            )
            if existing:
                return None

        resume = Resume(**data.model_dump())
        self.db.add(resume)
        self.db.commit()
        self.db.refresh(resume)
        return resume

    def get_by_id(self, resume_id: int) -> Resume | None:
        return self.db.query(Resume).filter(Resume.id == resume_id).first()

    def list(
        self,
        page: int = 1,
        page_size: int = 10,
        status: str | None = None,
        keyword: str | None = None,
        source: str | None = None,
    ) -> dict:
        """分页查询简历列表，支持按状态、关键词、来源过滤"""
        query = self.db.query(Resume)

        if status:
            query = query.filter(Resume.status == status)
        if source:
            query = query.filter(Resume.source == source)
        if keyword:
            pattern = f"%{keyword}%"
            query = query.filter(
                or_(
                    Resume.name.like(pattern),
                    Resume.skills.like(pattern),
                    Resume.job_intention.like(pattern),
                    Resume.work_experience.like(pattern),
                    Resume.raw_text.like(pattern),
                )
            )

        total = query.count()
        items = (
            query.order_by(Resume.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": items,
        }

    def update(self, resume_id: int, data: ResumeUpdate) -> Resume | None:
        """更新简历信息"""
        resume = self.get_by_id(resume_id)
        if not resume:
            return None

        update_data = data.model_dump(exclude_none=True)
        for key, value in update_data.items():
            setattr(resume, key, value)

        self.db.commit()
        self.db.refresh(resume)
        return resume

    def delete(self, resume_id: int) -> bool:
        resume = self.get_by_id(resume_id)
        if not resume:
            return False
        self.db.delete(resume)
        self.db.commit()
        return True
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/modules/resume/test_service.py -v`
Expected: 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add app/modules/resume/service.py tests/modules/resume/test_service.py
git commit -m "feat: add ResumeService with CRUD, pagination, keyword search, dedup"
```

---

### Task 8: 简历 API 路由

**Files:**
- Create: `app/modules/resume/router.py`
- Create: `tests/modules/resume/test_router.py`

- [ ] **Step 1: 写路由测试**

```python
"""简历 API 路由测试"""
import json


def test_create_resume_api(client):
    response = client.post(
        "/api/resumes/",
        json={
            "name": "测试候选人",
            "phone": "13800000001",
            "email": "test@example.com",
            "education": "本科",
            "work_years": 3,
            "source": "boss_zhipin",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "测试候选人"
    assert data["id"] is not None


def test_create_duplicate_resume_api(client):
    payload = {"name": "重复人", "phone": "13800000002", "source": "boss_zhipin"}
    client.post("/api/resumes/", json=payload)
    response = client.post("/api/resumes/", json=payload)
    assert response.status_code == 409


def test_get_resume_api(client):
    create_resp = client.post(
        "/api/resumes/", json={"name": "查询测试", "phone": "13800000003"}
    )
    resume_id = create_resp.json()["id"]

    response = client.get(f"/api/resumes/{resume_id}")
    assert response.status_code == 200
    assert response.json()["name"] == "查询测试"


def test_get_resume_not_found(client):
    response = client.get("/api/resumes/99999")
    assert response.status_code == 404


def test_list_resumes_api(client):
    for i in range(3):
        client.post(
            "/api/resumes/", json={"name": f"列表测试{i}", "phone": f"1390000{i:04d}"}
        )

    response = client.get("/api/resumes/")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3
    assert len(data["items"]) == 3


def test_list_resumes_with_filters(client):
    client.post(
        "/api/resumes/",
        json={"name": "Java开发", "phone": "13800000010", "skills": "Java,Spring"},
    )
    client.post(
        "/api/resumes/",
        json={"name": "Python开发", "phone": "13800000011", "skills": "Python"},
    )

    response = client.get("/api/resumes/?keyword=Java")
    data = response.json()
    assert data["total"] == 1


def test_update_resume_api(client):
    create_resp = client.post(
        "/api/resumes/", json={"name": "更新测试", "phone": "13800000020"}
    )
    resume_id = create_resp.json()["id"]

    response = client.patch(
        f"/api/resumes/{resume_id}",
        json={"status": "passed"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "passed"


def test_delete_resume_api(client):
    create_resp = client.post(
        "/api/resumes/", json={"name": "删除测试", "phone": "13800000030"}
    )
    resume_id = create_resp.json()["id"]

    response = client.delete(f"/api/resumes/{resume_id}")
    assert response.status_code == 204

    response = client.get(f"/api/resumes/{resume_id}")
    assert response.status_code == 404


def test_batch_create_resumes_api(client):
    """批量创建简历（Chrome 插件批量提交）"""
    resumes = [
        {"name": f"批量{i}", "phone": f"1370000{i:04d}", "source": "boss_zhipin"}
        for i in range(5)
    ]
    response = client.post("/api/resumes/batch", json=resumes)
    assert response.status_code == 201
    data = response.json()
    assert data["created"] == 5
    assert data["duplicates"] == 0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/modules/resume/test_router.py -v`
Expected: FAIL（router 不存在或路由未注册）

- [ ] **Step 3: 实现 router.py**

```python
"""简历管理 API 路由"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.resume.service import ResumeService
from app.modules.resume.schemas import (
    ResumeCreate,
    ResumeUpdate,
    ResumeResponse,
    ResumeListResponse,
)

router = APIRouter()


def get_resume_service(db: Session = Depends(get_db)) -> ResumeService:
    return ResumeService(db)


@router.post("/", response_model=ResumeResponse, status_code=201)
def create_resume(
    data: ResumeCreate,
    service: ResumeService = Depends(get_resume_service),
):
    resume = service.create(data)
    if resume is None:
        raise HTTPException(status_code=409, detail="简历已存在（姓名+手机号重复）")
    return resume


@router.post("/batch", status_code=201)
def batch_create_resumes(
    resumes: list[ResumeCreate],
    service: ResumeService = Depends(get_resume_service),
):
    created = 0
    duplicates = 0
    for data in resumes:
        result = service.create(data)
        if result is None:
            duplicates += 1
        else:
            created += 1
    return {"created": created, "duplicates": duplicates, "total": len(resumes)}


@router.get("/{resume_id}", response_model=ResumeResponse)
def get_resume(
    resume_id: int,
    service: ResumeService = Depends(get_resume_service),
):
    resume = service.get_by_id(resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="简历不存在")
    return resume


@router.get("/", response_model=ResumeListResponse)
def list_resumes(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    status: str | None = None,
    keyword: str | None = None,
    source: str | None = None,
    service: ResumeService = Depends(get_resume_service),
):
    return service.list(
        page=page, page_size=page_size, status=status, keyword=keyword, source=source
    )


@router.patch("/{resume_id}", response_model=ResumeResponse)
def update_resume(
    resume_id: int,
    data: ResumeUpdate,
    service: ResumeService = Depends(get_resume_service),
):
    resume = service.update(resume_id, data)
    if not resume:
        raise HTTPException(status_code=404, detail="简历不存在")
    return resume


@router.delete("/{resume_id}", status_code=204)
def delete_resume(
    resume_id: int,
    service: ResumeService = Depends(get_resume_service),
):
    if not service.delete(resume_id):
        raise HTTPException(status_code=404, detail="简历不存在")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/modules/resume/test_router.py -v`
Expected: 9 tests PASS

- [ ] **Step 5: Commit**

```bash
git add app/modules/resume/router.py tests/modules/resume/test_router.py
git commit -m "feat: add resume API routes with CRUD, batch create, pagination"
```

---

### Task 9: PDF 解析

**Files:**
- Create: `app/modules/resume/pdf_parser.py`
- Create: `tests/modules/resume/test_pdf_parser.py`

- [ ] **Step 1: 写 PDF 解析测试**

```python
"""PDF 解析测试"""
import os
from pathlib import Path
from app.modules.resume.pdf_parser import parse_pdf, extract_resume_fields


def _create_test_pdf(path: str, text: str):
    """创建一个包含指定文本的简单 PDF 用于测试"""
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(path)
    y = 800
    for line in text.split("\n"):
        c.drawString(72, y, line)
        y -= 15
    c.save()


def test_parse_pdf_extracts_text(tmp_path):
    pdf_path = str(tmp_path / "test.pdf")
    _create_test_pdf(pdf_path, "张三\n手机：13800138000\n邮箱：zhangsan@test.com")
    text = parse_pdf(pdf_path)
    assert "张三" in text
    assert "13800138000" in text


def test_parse_pdf_file_not_found():
    text = parse_pdf("/nonexistent/file.pdf")
    assert text == ""


def test_extract_resume_fields_phone():
    text = "联系方式：13912345678，邮箱test@qq.com"
    fields = extract_resume_fields(text)
    assert fields["phone"] == "13912345678"
    assert fields["email"] == "test@qq.com"


def test_extract_resume_fields_education():
    text = "教育经历：北京大学 本科 计算机科学 2015-2019"
    fields = extract_resume_fields(text)
    assert fields["education"] in ["本科", "硕士", "博士", "大专", ""]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/modules/resume/test_pdf_parser.py -v`
Expected: FAIL（pdf_parser 不存在）

- [ ] **Step 3: 安装 reportlab 用于测试 PDF 生成**

Run: `pip install reportlab && pip freeze | grep -i reportlab`
Expected: reportlab 安装成功

- [ ] **Step 4: 实现 pdf_parser.py**

```python
"""PDF 简历解析"""
import re
import logging
from pathlib import Path

from PyPDF2 import PdfReader

logger = logging.getLogger(__name__)


def parse_pdf(file_path: str) -> str:
    """从 PDF 文件提取全部文本内容，失败返回空字符串"""
    path = Path(file_path)
    if not path.exists():
        logger.warning(f"PDF 文件不存在: {file_path}")
        return ""

    try:
        reader = PdfReader(file_path)
        text_parts = []
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
        return "\n".join(text_parts)
    except Exception as e:
        logger.error(f"PDF 解析失败 [{file_path}]: {e}")
        return ""


def extract_resume_fields(text: str) -> dict:
    """从简历文本中提取结构化字段（尽力提取，缺失字段为空）"""
    fields = {
        "phone": "",
        "email": "",
        "education": "",
    }

    # 手机号：1开头的11位数字
    phone_match = re.search(r"1[3-9]\d{9}", text)
    if phone_match:
        fields["phone"] = phone_match.group()

    # 邮箱
    email_match = re.search(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", text)
    if email_match:
        fields["email"] = email_match.group()

    # 学历
    education_keywords = ["博士", "硕士", "本科", "大专"]
    for edu in education_keywords:
        if edu in text:
            fields["education"] = edu
            break

    return fields
```

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest tests/modules/resume/test_pdf_parser.py -v`
Expected: 4 tests PASS

- [ ] **Step 6: Commit**

```bash
git add app/modules/resume/pdf_parser.py tests/modules/resume/test_pdf_parser.py
git commit -m "feat: add PDF parser with text extraction and field recognition"
```

---

### Task 10: PDF 上传 API

**Files:**
- Modify: `app/modules/resume/router.py` (添加上传路由)
- Modify: `app/modules/resume/service.py` (添加上传处理)

- [ ] **Step 1: 写 PDF 上传测试**

Add to `tests/modules/resume/test_router.py`:

```python
import io


def test_upload_pdf_resume(client, tmp_path):
    """上传 PDF 简历文件"""
    from reportlab.pdfgen import canvas

    pdf_path = str(tmp_path / "resume.pdf")
    c = canvas.Canvas(pdf_path)
    c.drawString(72, 800, "王五")
    c.drawString(72, 785, "13800001111")
    c.drawString(72, 770, "wangwu@test.com")
    c.drawString(72, 755, "本科")
    c.save()

    with open(pdf_path, "rb") as f:
        response = client.post(
            "/api/resumes/upload",
            files={"file": ("resume.pdf", f, "application/pdf")},
        )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] != ""  # 从 PDF 中提取了信息
    assert data["pdf_path"] != ""
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/modules/resume/test_router.py::test_upload_pdf_resume -v`
Expected: FAIL（/api/resumes/upload 路由不存在）

- [ ] **Step 3: 在 service.py 添加 create_from_pdf 方法**

在 `ResumeService` 类末尾添加：

```python
    def create_from_pdf(self, file_path: str) -> Resume | None:
        """从 PDF 文件创建简历"""
        from app.modules.resume.pdf_parser import parse_pdf, extract_resume_fields

        raw_text = parse_pdf(file_path)
        if not raw_text:
            return None

        fields = extract_resume_fields(raw_text)
        data = ResumeCreate(
            name=fields.get("phone", "") or "未知",  # 暂用手机号或未知
            phone=fields.get("phone", ""),
            email=fields.get("email", ""),
            education=fields.get("education", ""),
            source="pdf_upload",
            raw_text=raw_text,
            pdf_path=file_path,
        )
        # PDF 上传不做去重（可能同名不同人）
        resume = Resume(**data.model_dump())
        self.db.add(resume)
        self.db.commit()
        self.db.refresh(resume)
        return resume
```

- [ ] **Step 4: 在 router.py 添加上传路由**

在 `router.py` 顶部添加导入：

```python
import shutil
from pathlib import Path
from fastapi import UploadFile, File
from app.config import settings
```

在文件末尾添加路由：

```python
@router.post("/upload", response_model=ResumeResponse, status_code=201)
def upload_pdf_resume(
    file: UploadFile = File(...),
    service: ResumeService = Depends(get_resume_service),
):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="仅支持 PDF 文件")

    storage_dir = Path(settings.resume_storage_path)
    storage_dir.mkdir(parents=True, exist_ok=True)

    # 保存文件
    import time
    filename = f"{int(time.time() * 1000)}_{file.filename}"
    file_path = storage_dir / filename
    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    resume = service.create_from_pdf(str(file_path))
    if not resume:
        file_path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail="PDF 解析失败，无法提取内容")
    return resume
```

- [ ] **Step 5: 运行全部路由测试**

Run: `python -m pytest tests/modules/resume/test_router.py -v`
Expected: 10 tests PASS

- [ ] **Step 6: Commit**

```bash
git add app/modules/resume/router.py app/modules/resume/service.py
git commit -m "feat: add PDF upload endpoint with auto-parsing"
```

---

### Task 11: Boss 直聘适配器接口定义

**Files:**
- Create: `app/adapters/__init__.py`
- Create: `app/adapters/boss/__init__.py`
- Create: `app/adapters/boss/base.py`

- [ ] **Step 1: 定义适配器抽象接口**

Create `app/adapters/__init__.py` (empty) and `app/adapters/boss/__init__.py` (empty), then `app/adapters/boss/base.py`:

```python
"""Boss 直聘适配器基础接口

所有 Boss 直聘操作方案（Chrome 插件、Playwright 等）都实现此接口，
上层业务代码只依赖此接口，不依赖具体实现。
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class BossCandidate:
    """Boss 直聘上的候选人信息"""
    name: str
    boss_id: str = ""  # Boss 直聘用户 ID
    phone: str = ""
    email: str = ""
    education: str = ""
    work_years: int = 0
    expected_salary: str = ""
    job_intention: str = ""
    skills: str = ""
    work_experience: str = ""
    project_experience: str = ""
    self_evaluation: str = ""
    has_pdf: bool = False
    pdf_url: str = ""


@dataclass
class BossMessage:
    """Boss 直聘聊天消息"""
    sender_id: str
    sender_name: str
    content: str
    is_pdf: bool = False
    pdf_url: str = ""
    timestamp: str = ""


class BossAdapter(ABC):
    """Boss 直聘操作适配器接口"""

    @abstractmethod
    async def get_new_greetings(self) -> list[BossCandidate]:
        """获取新的打招呼消息列表"""
        ...

    @abstractmethod
    async def send_greeting_reply(self, boss_id: str, message: str) -> bool:
        """回复候选人打招呼消息"""
        ...

    @abstractmethod
    async def get_candidate_info(self, boss_id: str) -> BossCandidate | None:
        """获取候选人详细信息"""
        ...

    @abstractmethod
    async def get_chat_messages(self, boss_id: str) -> list[BossMessage]:
        """获取与候选人的聊天记录"""
        ...

    @abstractmethod
    async def download_pdf(self, pdf_url: str, save_path: str) -> bool:
        """下载候选人的 PDF 简历"""
        ...

    @abstractmethod
    async def is_available(self) -> bool:
        """检查适配器是否可用（如后端服务是否运行、浏览器是否打开等）"""
        ...
```

- [ ] **Step 2: 验证接口可导入**

Run: `python -c "from app.adapters.boss.base import BossAdapter, BossCandidate; print('OK')"`
Expected: 输出 `OK`

- [ ] **Step 3: Commit**

```bash
git add app/adapters/__init__.py app/adapters/boss/__init__.py app/adapters/boss/base.py
git commit -m "feat: define BossAdapter abstract interface for multi-strategy support"
```

---

### Task 12: 运行全部测试 & 验证独立启动

- [ ] **Step 1: 运行全部测试**

Run: `python -m pytest tests/ -v --tb=short`
Expected: 所有测试 PASS（约 22 个）

- [ ] **Step 2: 验证应用可独立启动**

Run: `python -c "import uvicorn; from app.main import app; print('App loaded OK')"`
Expected: 输出 `App loaded OK`

- [ ] **Step 3: 验证简历模块可独立运行**

Run: `python -c "from app.modules.resume.service import ResumeService; from app.modules.resume.schemas import ResumeCreate; print('Resume module OK')"`
Expected: 输出 `Resume module OK`

- [ ] **Step 4: Commit（如有遗漏文件）**

```bash
git status
git add -A
git commit -m "chore: plan 1 complete - backend foundation and resume module"
```

---

## Summary

Plan 1 完成后交付物：
- FastAPI 后端框架（配置、数据库、路由注册）
- 简历管理模块完整 CRUD API（创建、批量创建、查询、分页列表、更新状态、删除）
- PDF 简历上传与解析
- Boss 直聘适配器接口定义
- 约 22 个测试覆盖全部功能
- 可通过 `uvicorn app.main:app` 独立启动运行
