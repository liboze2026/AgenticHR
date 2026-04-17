# Plan 2: 筛选规则 + AI 评估模块 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现岗位管理、硬性条件筛选、AI 软性评估（可选开关），使 HR 能配置筛选规则并对简历进行两阶段筛选。

**Architecture:** 两个独立模块：screening（岗位管理+硬性条件过滤）和 ai_evaluation（大模型评分）。screening 模块可独立运行，ai_evaluation 通过适配器调用外部 AI 服务，支持开关控制。

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic v2, httpx (AI API 调用), pytest

---

## File Structure

```
app/modules/
├── screening/
│   ├── __init__.py
│   ├── models.py          # Job 岗位模型, ScreeningRule 筛选规则模型
│   ├── schemas.py          # 输入输出结构
│   ├── service.py          # 岗位管理 + 硬性条件筛选逻辑
│   └── router.py           # API 路由
├── ai_evaluation/
│   ├── __init__.py
│   ├── schemas.py          # AI 评估输入输出
│   ├── service.py          # AI 评估业务逻辑
│   └── router.py           # API 路由
app/adapters/
└── ai_provider.py          # AI 大模型适配器
tests/modules/
├── screening/
│   ├── __init__.py
│   ├── test_models.py
│   ├── test_service.py
│   └── test_router.py
└── ai_evaluation/
    ├── __init__.py
    ├── test_service.py
    └── test_router.py
```

---

### Task 1: 岗位数据模型

**Files:**
- Create: `app/modules/screening/__init__.py`
- Create: `app/modules/screening/models.py`
- Create: `tests/modules/screening/__init__.py`
- Create: `tests/modules/screening/test_models.py`

- [ ] **Step 1: 写模型测试**

```python
"""岗位数据模型测试"""
from app.modules.screening.models import Job


def test_create_job(db_session):
    job = Job(
        title="Python后端开发",
        department="技术部",
        education_min="本科",
        work_years_min=3,
        work_years_max=10,
        salary_min=15000,
        salary_max=30000,
        required_skills="Python,FastAPI",
        soft_requirements="有大厂经历优先，熟悉微服务架构",
        greeting_templates="您好，请发送一份简历过来|你好，方便发一下简历吗",
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)

    assert job.id is not None
    assert job.title == "Python后端开发"
    assert job.is_active is True


def test_job_default_values(db_session):
    job = Job(title="测试岗位")
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)

    assert job.work_years_min == 0
    assert job.work_years_max == 99
    assert job.is_active is True
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/modules/screening/test_models.py -v`

- [ ] **Step 3: 实现 models.py**

```python
"""岗位与筛选规则数据模型"""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, Float, Boolean, DateTime

from app.database import Base


class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(200), nullable=False, index=True)
    department = Column(String(100), default="")
    
    # 硬性条件
    education_min = Column(String(50), default="")  # 大专/本科/硕士/博士
    work_years_min = Column(Integer, default=0)
    work_years_max = Column(Integer, default=99)
    salary_min = Column(Float, default=0)
    salary_max = Column(Float, default=0)
    required_skills = Column(Text, default="")  # 逗号分隔的必备技能关键词
    
    # 软性要求（AI 评估用）
    soft_requirements = Column(Text, default="")
    
    # 打招呼话术模板（竖线分隔多条）
    greeting_templates = Column(Text, default="")
    
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
```

- [ ] **Step 4: 确保 conftest.py 导入新模型**

在 `tests/conftest.py` 的 `db_engine` fixture 中，在 `Base.metadata.create_all` 之前添加导入：
```python
import app.modules.screening.models  # noqa: F401
```

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest tests/modules/screening/test_models.py -v`

- [ ] **Step 6: Commit**

```bash
git add app/modules/screening/ tests/modules/screening/ tests/conftest.py
git commit -m "feat: add Job model for position management"
```

---

### Task 2: 岗位 Schema + Service + Router

**Files:**
- Create: `app/modules/screening/schemas.py`
- Create: `app/modules/screening/service.py`
- Create: `app/modules/screening/router.py`
- Create: `tests/modules/screening/test_service.py`
- Create: `tests/modules/screening/test_router.py`
- Modify: `app/main.py` (注册路由)

- [ ] **Step 1: 创建 schemas.py**

```python
"""岗位筛选输入/输出数据结构"""
from datetime import datetime
from pydantic import BaseModel, Field


class JobCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    department: str = Field(default="", max_length=100)
    education_min: str = Field(default="", max_length=50)
    work_years_min: int = Field(default=0, ge=0)
    work_years_max: int = Field(default=99, ge=0)
    salary_min: float = Field(default=0, ge=0)
    salary_max: float = Field(default=0, ge=0)
    required_skills: str = Field(default="", description="逗号分隔")
    soft_requirements: str = Field(default="")
    greeting_templates: str = Field(default="", description="竖线分隔多条话术")


class JobUpdate(BaseModel):
    title: str | None = None
    department: str | None = None
    education_min: str | None = None
    work_years_min: int | None = None
    work_years_max: int | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    required_skills: str | None = None
    soft_requirements: str | None = None
    greeting_templates: str | None = None
    is_active: bool | None = None


class JobResponse(BaseModel):
    id: int
    title: str
    department: str
    education_min: str
    work_years_min: int
    work_years_max: int
    salary_min: float
    salary_max: float
    required_skills: str
    soft_requirements: str
    greeting_templates: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class JobListResponse(BaseModel):
    total: int
    items: list[JobResponse]


class ScreeningResult(BaseModel):
    """单个简历的筛选结果"""
    resume_id: int
    resume_name: str
    passed: bool
    reject_reasons: list[str] = Field(default_factory=list)


class ScreeningResponse(BaseModel):
    """批量筛选结果"""
    job_id: int
    total: int
    passed: int
    rejected: int
    results: list[ScreeningResult]
```

- [ ] **Step 2: 写 service 测试**

```python
"""岗位管理与硬性条件筛选测试"""
from app.modules.screening.service import ScreeningService
from app.modules.screening.schemas import JobCreate, JobUpdate
from app.modules.resume.service import ResumeService
from app.modules.resume.schemas import ResumeCreate


def _create_test_resumes(db_session):
    """创建测试简历数据"""
    rs = ResumeService(db_session)
    rs.create(ResumeCreate(
        name="候选人A", phone="10000000001", education="硕士",
        work_years=5, expected_salary_min=20000, expected_salary_max=30000,
        skills="Python,FastAPI,Docker", source="boss_zhipin",
    ))
    rs.create(ResumeCreate(
        name="候选人B", phone="10000000002", education="大专",
        work_years=1, expected_salary_min=8000, expected_salary_max=12000,
        skills="Python", source="boss_zhipin",
    ))
    rs.create(ResumeCreate(
        name="候选人C", phone="10000000003", education="本科",
        work_years=3, expected_salary_min=15000, expected_salary_max=20000,
        skills="Java,Spring,MySQL", source="boss_zhipin",
    ))


def test_create_job(db_session):
    service = ScreeningService(db_session)
    job = service.create_job(JobCreate(
        title="Python开发", education_min="本科",
        work_years_min=2, required_skills="Python",
    ))
    assert job.id is not None
    assert job.title == "Python开发"


def test_list_jobs(db_session):
    service = ScreeningService(db_session)
    service.create_job(JobCreate(title="岗位1"))
    service.create_job(JobCreate(title="岗位2"))
    result = service.list_jobs()
    assert result["total"] == 2


def test_update_job(db_session):
    service = ScreeningService(db_session)
    job = service.create_job(JobCreate(title="旧标题"))
    updated = service.update_job(job.id, JobUpdate(title="新标题"))
    assert updated.title == "新标题"


def test_screen_by_education(db_session):
    """学历筛选：要求本科，大专不通过"""
    _create_test_resumes(db_session)
    service = ScreeningService(db_session)
    job = service.create_job(JobCreate(title="测试岗", education_min="本科"))
    result = service.screen_resumes(job.id)
    assert result["passed"] == 2  # 硕士+本科通过
    assert result["rejected"] == 1  # 大专不通过


def test_screen_by_work_years(db_session):
    """工作年限筛选"""
    _create_test_resumes(db_session)
    service = ScreeningService(db_session)
    job = service.create_job(JobCreate(title="测试岗", work_years_min=3))
    result = service.screen_resumes(job.id)
    assert result["passed"] == 2  # A(5年)+C(3年)
    assert result["rejected"] == 1  # B(1年)


def test_screen_by_skills(db_session):
    """技能关键词筛选"""
    _create_test_resumes(db_session)
    service = ScreeningService(db_session)
    job = service.create_job(JobCreate(title="测试岗", required_skills="Python"))
    result = service.screen_resumes(job.id)
    assert result["passed"] == 2  # A+B有Python
    assert result["rejected"] == 1  # C只有Java


def test_screen_combined(db_session):
    """组合筛选：本科+3年+Python"""
    _create_test_resumes(db_session)
    service = ScreeningService(db_session)
    job = service.create_job(JobCreate(
        title="测试岗", education_min="本科",
        work_years_min=3, required_skills="Python",
    ))
    result = service.screen_resumes(job.id)
    assert result["passed"] == 1  # 只有A通过
```

- [ ] **Step 3: 实现 service.py**

```python
"""岗位管理与硬性条件筛选"""
from sqlalchemy.orm import Session

from app.modules.screening.models import Job
from app.modules.screening.schemas import JobCreate, JobUpdate
from app.modules.resume.models import Resume


# 学历等级映射（用于比较）
EDUCATION_LEVELS = {"大专": 1, "本科": 2, "硕士": 3, "博士": 4}


class ScreeningService:
    def __init__(self, db: Session):
        self.db = db

    def create_job(self, data: JobCreate) -> Job:
        job = Job(**data.model_dump())
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)
        return job

    def get_job(self, job_id: int) -> Job | None:
        return self.db.query(Job).filter(Job.id == job_id).first()

    def list_jobs(self, active_only: bool = False) -> dict:
        query = self.db.query(Job)
        if active_only:
            query = query.filter(Job.is_active == True)
        items = query.order_by(Job.created_at.desc()).all()
        return {"total": len(items), "items": items}

    def update_job(self, job_id: int, data: JobUpdate) -> Job | None:
        job = self.get_job(job_id)
        if not job:
            return None
        for key, value in data.model_dump(exclude_none=True).items():
            setattr(job, key, value)
        self.db.commit()
        self.db.refresh(job)
        return job

    def delete_job(self, job_id: int) -> bool:
        job = self.get_job(job_id)
        if not job:
            return False
        self.db.delete(job)
        self.db.commit()
        return True

    def screen_resumes(self, job_id: int, resume_ids: list[int] | None = None) -> dict:
        """对简历执行硬性条件筛选"""
        job = self.get_job(job_id)
        if not job:
            return {"job_id": job_id, "total": 0, "passed": 0, "rejected": 0, "results": []}

        query = self.db.query(Resume).filter(Resume.status == "pending")
        if resume_ids:
            query = query.filter(Resume.id.in_(resume_ids))
        resumes = query.all()

        results = []
        passed_count = 0
        rejected_count = 0

        for resume in resumes:
            reject_reasons = []

            # 学历检查
            if job.education_min:
                min_level = EDUCATION_LEVELS.get(job.education_min, 0)
                resume_level = EDUCATION_LEVELS.get(resume.education, 0)
                if resume_level < min_level:
                    reject_reasons.append(f"学历不符：要求{job.education_min}，实际{resume.education or '未知'}")

            # 工作年限检查
            if resume.work_years < job.work_years_min:
                reject_reasons.append(f"工作年限不足：要求{job.work_years_min}年，实际{resume.work_years}年")
            if resume.work_years > job.work_years_max:
                reject_reasons.append(f"工作年限超出：最高{job.work_years_max}年，实际{resume.work_years}年")

            # 薪资检查（如果岗位和简历都填了）
            if job.salary_max > 0 and resume.expected_salary_min > 0:
                if resume.expected_salary_min > job.salary_max:
                    reject_reasons.append(f"薪资期望过高：岗位上限{job.salary_max}，期望{resume.expected_salary_min}")

            # 必备技能检查
            if job.required_skills:
                required = [s.strip().lower() for s in job.required_skills.split(",") if s.strip()]
                resume_skills = (resume.skills or "").lower()
                resume_text = (resume.raw_text or "").lower()
                for skill in required:
                    if skill not in resume_skills and skill not in resume_text:
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

        self.db.commit()
        return {
            "job_id": job_id,
            "total": len(resumes),
            "passed": passed_count,
            "rejected": rejected_count,
            "results": results,
        }
```

- [ ] **Step 4: 实现 router.py**

```python
"""岗位管理与筛选 API 路由"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.screening.service import ScreeningService
from app.modules.screening.schemas import (
    JobCreate, JobUpdate, JobResponse, JobListResponse, ScreeningResponse,
)

router = APIRouter()


def get_screening_service(db: Session = Depends(get_db)) -> ScreeningService:
    return ScreeningService(db)


@router.post("/jobs", response_model=JobResponse, status_code=201)
def create_job(data: JobCreate, service: ScreeningService = Depends(get_screening_service)):
    return service.create_job(data)


@router.get("/jobs", response_model=JobListResponse)
def list_jobs(
    active_only: bool = False,
    service: ScreeningService = Depends(get_screening_service),
):
    return service.list_jobs(active_only=active_only)


@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: int, service: ScreeningService = Depends(get_screening_service)):
    job = service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="岗位不存在")
    return job


@router.patch("/jobs/{job_id}", response_model=JobResponse)
def update_job(job_id: int, data: JobUpdate, service: ScreeningService = Depends(get_screening_service)):
    job = service.update_job(job_id, data)
    if not job:
        raise HTTPException(status_code=404, detail="岗位不存在")
    return job


@router.delete("/jobs/{job_id}", status_code=204)
def delete_job(job_id: int, service: ScreeningService = Depends(get_screening_service)):
    if not service.delete_job(job_id):
        raise HTTPException(status_code=404, detail="岗位不存在")


@router.post("/jobs/{job_id}/screen", response_model=ScreeningResponse)
def screen_resumes(
    job_id: int,
    resume_ids: list[int] | None = None,
    service: ScreeningService = Depends(get_screening_service),
):
    job = service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="岗位不存在")
    return service.screen_resumes(job_id, resume_ids)
```

- [ ] **Step 5: 写路由测试**

```python
"""岗位管理与筛选 API 路由测试"""


def test_create_job_api(client):
    response = client.post("/api/screening/jobs", json={
        "title": "Python开发",
        "education_min": "本科",
        "work_years_min": 2,
        "required_skills": "Python,Django",
    })
    assert response.status_code == 201
    assert response.json()["title"] == "Python开发"


def test_list_jobs_api(client):
    client.post("/api/screening/jobs", json={"title": "岗位A"})
    client.post("/api/screening/jobs", json={"title": "岗位B"})
    response = client.get("/api/screening/jobs")
    assert response.status_code == 200
    assert response.json()["total"] == 2


def test_update_job_api(client):
    resp = client.post("/api/screening/jobs", json={"title": "旧"})
    job_id = resp.json()["id"]
    response = client.patch(f"/api/screening/jobs/{job_id}", json={"title": "新"})
    assert response.status_code == 200
    assert response.json()["title"] == "新"


def test_delete_job_api(client):
    resp = client.post("/api/screening/jobs", json={"title": "删除测试"})
    job_id = resp.json()["id"]
    response = client.delete(f"/api/screening/jobs/{job_id}")
    assert response.status_code == 204


def test_screen_resumes_api(client):
    # 创建岗位
    job_resp = client.post("/api/screening/jobs", json={
        "title": "测试筛选",
        "education_min": "本科",
        "work_years_min": 2,
        "required_skills": "Python",
    })
    job_id = job_resp.json()["id"]

    # 创建简历
    client.post("/api/resumes/", json={
        "name": "合格候选人", "phone": "10000000101",
        "education": "本科", "work_years": 3, "skills": "Python,Django",
    })
    client.post("/api/resumes/", json={
        "name": "不合格候选人", "phone": "10000000102",
        "education": "大专", "work_years": 1, "skills": "HTML",
    })

    # 执行筛选
    response = client.post(f"/api/screening/jobs/{job_id}/screen")
    assert response.status_code == 200
    data = response.json()
    assert data["passed"] == 1
    assert data["rejected"] == 1
```

- [ ] **Step 6: 注册路由到 main.py**

在 `app/main.py` 添加：
```python
from app.modules.screening.router import router as screening_router
app.include_router(screening_router, prefix="/api/screening", tags=["screening"])
```

- [ ] **Step 7: 运行全部测试**

Run: `python -m pytest tests/ -v`

- [ ] **Step 8: Commit**

```bash
git add app/modules/screening/ tests/modules/screening/ app/main.py tests/conftest.py
git commit -m "feat: add job management and hard-condition resume screening"
```

---

### Task 3: AI 评估适配器

**Files:**
- Create: `app/adapters/ai_provider.py`

- [ ] **Step 1: 实现 AI 适配器**

```python
"""AI 大模型适配器

封装对外部 AI 服务的调用，支持 OpenAI 兼容接口（Claude、通义千问等均可通过此协议调用）。
"""
import logging
import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class AIProvider:
    """AI 大模型调用适配器"""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ):
        self.api_key = api_key or settings.ai_api_key
        self.base_url = (base_url or settings.ai_base_url).rstrip("/")
        self.model = model or settings.ai_model

    async def evaluate_resume(self, resume_text: str, job_requirements: str) -> dict:
        """评估简历与岗位的匹配度

        Returns:
            {
                "score": 0-100,
                "strengths": ["优势1", "优势2"],
                "risks": ["风险1", "风险2"],
                "recommendation": "推荐" | "待定" | "不推荐",
                "summary": "综合评价..."
            }
        """
        prompt = f"""你是一个专业的HR简历筛选助手。请根据岗位要求评估以下简历。

## 岗位要求
{job_requirements}

## 候选人简历
{resume_text}

## 请输出以下JSON格式（不要输出其他内容）：
{{
    "score": <0-100的匹配度评分>,
    "strengths": ["优势点1", "优势点2", "优势点3"],
    "risks": ["风险点1", "风险点2"],
    "recommendation": "<推荐|待定|不推荐>",
    "summary": "<一句话综合评价>"
}}"""

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.3,
                    },
                )
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                
                # 提取 JSON
                import json
                # 处理可能被 markdown 代码块包裹的情况
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0]
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0]
                
                return json.loads(content.strip())
        except Exception as e:
            logger.error(f"AI 评估失败: {e}")
            return {
                "score": -1,
                "strengths": [],
                "risks": [],
                "recommendation": "评估失败",
                "summary": f"AI 评估出错: {str(e)}",
            }

    def is_configured(self) -> bool:
        """检查 AI 服务是否已配置"""
        return bool(self.api_key and self.base_url and self.model)
```

- [ ] **Step 2: 验证导入**

Run: `python -c "from app.adapters.ai_provider import AIProvider; print('OK')"`

- [ ] **Step 3: Commit**

```bash
git add app/adapters/ai_provider.py
git commit -m "feat: add AI provider adapter with OpenAI-compatible interface"
```

---

### Task 4: AI 评估模块

**Files:**
- Create: `app/modules/ai_evaluation/__init__.py`
- Create: `app/modules/ai_evaluation/schemas.py`
- Create: `app/modules/ai_evaluation/service.py`
- Create: `app/modules/ai_evaluation/router.py`
- Create: `tests/modules/ai_evaluation/__init__.py`
- Create: `tests/modules/ai_evaluation/test_service.py`
- Create: `tests/modules/ai_evaluation/test_router.py`
- Modify: `app/main.py` (注册路由)

- [ ] **Step 1: 创建 schemas.py**

```python
"""AI 评估输入/输出数据结构"""
from pydantic import BaseModel, Field


class EvaluationRequest(BaseModel):
    """单个简历评估请求"""
    resume_id: int
    job_id: int


class BatchEvaluationRequest(BaseModel):
    """批量评估请求"""
    job_id: int
    resume_ids: list[int] | None = Field(None, description="为空则评估该岗位所有已通过硬性筛选的简历")


class EvaluationResult(BaseModel):
    """评估结果"""
    resume_id: int
    resume_name: str
    score: float
    strengths: list[str]
    risks: list[str]
    recommendation: str
    summary: str
    status: str  # success, failed


class BatchEvaluationResponse(BaseModel):
    """批量评估响应"""
    job_id: int
    total: int
    succeeded: int
    failed: int
    results: list[EvaluationResult]
```

- [ ] **Step 2: 实现 service.py**

```python
"""AI 简历评估业务逻辑"""
import logging
from sqlalchemy.orm import Session

from app.config import settings
from app.adapters.ai_provider import AIProvider
from app.modules.resume.models import Resume
from app.modules.screening.models import Job

logger = logging.getLogger(__name__)


class AIEvaluationService:
    def __init__(self, db: Session, ai_provider: AIProvider | None = None):
        self.db = db
        self.ai = ai_provider or AIProvider()

    async def evaluate_single(self, resume_id: int, job_id: int) -> dict:
        """评估单个简历"""
        resume = self.db.query(Resume).filter(Resume.id == resume_id).first()
        if not resume:
            return {"resume_id": resume_id, "resume_name": "", "status": "failed",
                    "score": -1, "strengths": [], "risks": [],
                    "recommendation": "错误", "summary": "简历不存在"}

        job = self.db.query(Job).filter(Job.id == job_id).first()
        if not job:
            return {"resume_id": resume_id, "resume_name": resume.name, "status": "failed",
                    "score": -1, "strengths": [], "risks": [],
                    "recommendation": "错误", "summary": "岗位不存在"}

        resume_text = resume.raw_text or f"姓名：{resume.name}\n学历：{resume.education}\n工作年限：{resume.work_years}\n技能：{resume.skills}\n工作经历：{resume.work_experience}\n项目经历：{resume.project_experience}"
        job_requirements = f"岗位：{job.title}\n学历要求：{job.education_min}\n工作年限：{job.work_years_min}-{job.work_years_max}年\n必备技能：{job.required_skills}\n其他要求：{job.soft_requirements}"

        result = await self.ai.evaluate_resume(resume_text, job_requirements)

        # 更新简历的 AI 评分
        if result.get("score", -1) >= 0:
            resume.ai_score = result["score"]
            resume.ai_summary = result.get("summary", "")
            self.db.commit()

        return {
            "resume_id": resume.id,
            "resume_name": resume.name,
            "score": result.get("score", -1),
            "strengths": result.get("strengths", []),
            "risks": result.get("risks", []),
            "recommendation": result.get("recommendation", "未知"),
            "summary": result.get("summary", ""),
            "status": "success" if result.get("score", -1) >= 0 else "failed",
        }

    async def evaluate_batch(self, job_id: int, resume_ids: list[int] | None = None) -> dict:
        """批量评估简历"""
        if resume_ids:
            resumes = self.db.query(Resume).filter(Resume.id.in_(resume_ids)).all()
        else:
            resumes = self.db.query(Resume).filter(Resume.status == "passed").all()

        results = []
        succeeded = 0
        failed = 0

        for resume in resumes:
            result = await self.evaluate_single(resume.id, job_id)
            results.append(result)
            if result["status"] == "success":
                succeeded += 1
            else:
                failed += 1

        # 按评分排序
        results.sort(key=lambda x: x.get("score", -1), reverse=True)

        return {
            "job_id": job_id,
            "total": len(resumes),
            "succeeded": succeeded,
            "failed": failed,
            "results": results,
        }
```

- [ ] **Step 3: 写 service 测试（使用 mock AI）**

```python
"""AI 评估 service 测试"""
import pytest
from unittest.mock import AsyncMock
from app.modules.ai_evaluation.service import AIEvaluationService
from app.modules.resume.models import Resume
from app.modules.screening.models import Job


class MockAIProvider:
    async def evaluate_resume(self, resume_text, job_requirements):
        return {
            "score": 85,
            "strengths": ["技能匹配", "经验丰富"],
            "risks": ["薪资偏高"],
            "recommendation": "推荐",
            "summary": "综合素质不错",
        }

    def is_configured(self):
        return True


@pytest.fixture
def ai_service(db_session):
    return AIEvaluationService(db_session, ai_provider=MockAIProvider())


@pytest.fixture
def test_data(db_session):
    job = Job(title="Python开发", education_min="本科", required_skills="Python", soft_requirements="有大厂经历优先")
    db_session.add(job)
    resume = Resume(name="测试候选人", phone="10000000001", education="本科", work_years=3, skills="Python,Django", status="passed")
    db_session.add(resume)
    db_session.commit()
    db_session.refresh(job)
    db_session.refresh(resume)
    return {"job_id": job.id, "resume_id": resume.id}


@pytest.mark.asyncio
async def test_evaluate_single(ai_service, test_data):
    result = await ai_service.evaluate_single(test_data["resume_id"], test_data["job_id"])
    assert result["status"] == "success"
    assert result["score"] == 85
    assert result["recommendation"] == "推荐"
    assert len(result["strengths"]) > 0


@pytest.mark.asyncio
async def test_evaluate_single_resume_not_found(ai_service, test_data):
    result = await ai_service.evaluate_single(99999, test_data["job_id"])
    assert result["status"] == "failed"


@pytest.mark.asyncio
async def test_evaluate_batch(ai_service, test_data, db_session):
    # 添加更多简历
    r2 = Resume(name="候选人2", phone="10000000002", skills="Python", status="passed")
    db_session.add(r2)
    db_session.commit()

    result = await ai_service.evaluate_batch(test_data["job_id"])
    assert result["total"] == 2
    assert result["succeeded"] == 2
    assert result["results"][0]["score"] >= result["results"][1]["score"]  # 按分数排序
```

- [ ] **Step 4: 实现 router.py**

```python
"""AI 评估 API 路由"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.adapters.ai_provider import AIProvider
from app.modules.ai_evaluation.service import AIEvaluationService
from app.modules.ai_evaluation.schemas import (
    EvaluationRequest, BatchEvaluationRequest,
    EvaluationResult, BatchEvaluationResponse,
)

router = APIRouter()


def get_ai_service(db: Session = Depends(get_db)) -> AIEvaluationService:
    return AIEvaluationService(db)


@router.post("/evaluate", response_model=EvaluationResult)
async def evaluate_resume(
    request: EvaluationRequest,
    service: AIEvaluationService = Depends(get_ai_service),
):
    if not settings.ai_enabled:
        raise HTTPException(status_code=400, detail="AI 功能未开启，请在设置中启用")
    return await service.evaluate_single(request.resume_id, request.job_id)


@router.post("/evaluate/batch", response_model=BatchEvaluationResponse)
async def batch_evaluate(
    request: BatchEvaluationRequest,
    service: AIEvaluationService = Depends(get_ai_service),
):
    if not settings.ai_enabled:
        raise HTTPException(status_code=400, detail="AI 功能未开启，请在设置中启用")
    return await service.evaluate_batch(request.job_id, request.resume_ids)


@router.get("/status")
def ai_status():
    """检查 AI 功能状态"""
    provider = AIProvider()
    return {
        "enabled": settings.ai_enabled,
        "configured": provider.is_configured(),
        "provider": settings.ai_provider,
        "model": settings.ai_model,
    }
```

- [ ] **Step 5: 写路由测试**

```python
"""AI 评估 API 路由测试"""
from unittest.mock import patch
from app.modules.resume.models import Resume
from app.modules.screening.models import Job


def test_ai_status(client):
    response = client.get("/api/ai/status")
    assert response.status_code == 200
    assert "enabled" in response.json()


def test_evaluate_when_disabled(client):
    """AI 未启用时返回 400"""
    response = client.post("/api/ai/evaluate", json={"resume_id": 1, "job_id": 1})
    assert response.status_code == 400
    assert "未开启" in response.json()["detail"]


def test_batch_evaluate_when_disabled(client):
    response = client.post("/api/ai/evaluate/batch", json={"job_id": 1})
    assert response.status_code == 400
```

- [ ] **Step 6: 注册路由到 main.py**

```python
from app.modules.ai_evaluation.router import router as ai_router
app.include_router(ai_router, prefix="/api/ai", tags=["ai_evaluation"])
```

- [ ] **Step 7: 运行全部测试**

Run: `python -m pytest tests/ -v`

- [ ] **Step 8: Commit**

```bash
git add app/modules/ai_evaluation/ app/adapters/ai_provider.py tests/modules/ai_evaluation/ app/main.py
git commit -m "feat: add AI evaluation module with mock-testable provider adapter"
```

---

### Task 5: 全部测试验证

- [ ] **Step 1: 运行全部测试**

Run: `python -m pytest tests/ -v --tb=short`
Expected: 所有测试通过

- [ ] **Step 2: 验证模块可独立导入**

```bash
python -c "from app.modules.screening.service import ScreeningService; print('Screening OK')"
python -c "from app.modules.ai_evaluation.service import AIEvaluationService; print('AI Eval OK')"
```

- [ ] **Step 3: Commit（如有遗漏）**

```bash
git status && git add -A && git commit -m "chore: plan 2 complete - screening and AI evaluation"
```
