# Plan 3: 日程协调 + 会议管理 + 通知模块 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 实现面试官日程管理、面试安排时段匹配、腾讯会议集成、邮件/飞书/模板通知，使 HR 能协调面试官和候选人时间并一键发送通知。

**Architecture:** 三个独立模块 scheduling（日程协调）、meeting（会议管理）、notification（通知），通过内部 API 通信。飞书日历/腾讯会议通过适配器封装。

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic v2, httpx, smtplib/email, pytest

---

### Task 1: 日程协调模块 — 数据模型 + Service

**Files:**
- Create: `app/modules/scheduling/__init__.py`
- Create: `app/modules/scheduling/models.py`
- Create: `app/modules/scheduling/schemas.py`
- Create: `app/modules/scheduling/service.py`
- Create: `tests/modules/scheduling/__init__.py`
- Create: `tests/modules/scheduling/test_service.py`
- Modify: `tests/conftest.py` (import new models)

**models.py:**
```python
"""面试官与面试安排数据模型"""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey

from app.database import Base


class Interviewer(Base):
    __tablename__ = "interviewers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    feishu_user_id = Column(String(100), default="")
    email = Column(String(200), default="")
    department = Column(String(100), default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


class InterviewerAvailability(Base):
    __tablename__ = "interviewer_availability"

    id = Column(Integer, primary_key=True, autoincrement=True)
    interviewer_id = Column(Integer, ForeignKey("interviewers.id"), nullable=False)
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=False)
    source = Column(String(50), default="manual")  # manual, feishu_calendar


class Interview(Base):
    __tablename__ = "interviews"

    id = Column(Integer, primary_key=True, autoincrement=True)
    resume_id = Column(Integer, ForeignKey("resumes.id"), nullable=False)
    interviewer_id = Column(Integer, ForeignKey("interviewers.id"), nullable=False)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=True)
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=False)
    meeting_link = Column(String(500), default="")
    meeting_password = Column(String(100), default="")
    status = Column(String(20), default="scheduled")  # scheduled, completed, cancelled
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
```

**schemas.py:**
```python
"""日程协调输入/输出数据结构"""
from datetime import datetime
from pydantic import BaseModel, Field


class InterviewerCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    feishu_user_id: str = Field(default="")
    email: str = Field(default="")
    department: str = Field(default="")


class InterviewerResponse(BaseModel):
    id: int
    name: str
    feishu_user_id: str
    email: str
    department: str
    created_at: datetime
    model_config = {"from_attributes": True}


class InterviewerListResponse(BaseModel):
    total: int
    items: list[InterviewerResponse]


class AvailabilityCreate(BaseModel):
    interviewer_id: int
    start_time: datetime
    end_time: datetime
    source: str = "manual"


class AvailabilityResponse(BaseModel):
    id: int
    interviewer_id: int
    start_time: datetime
    end_time: datetime
    source: str
    model_config = {"from_attributes": True}


class CandidateAvailability(BaseModel):
    start_time: datetime
    end_time: datetime


class InterviewCreate(BaseModel):
    resume_id: int
    interviewer_id: int
    job_id: int | None = None
    start_time: datetime
    end_time: datetime
    meeting_link: str = ""
    meeting_password: str = ""
    notes: str = ""


class InterviewUpdate(BaseModel):
    start_time: datetime | None = None
    end_time: datetime | None = None
    meeting_link: str | None = None
    meeting_password: str | None = None
    status: str | None = None
    notes: str | None = None


class InterviewResponse(BaseModel):
    id: int
    resume_id: int
    interviewer_id: int
    job_id: int | None
    start_time: datetime
    end_time: datetime
    meeting_link: str
    meeting_password: str
    status: str
    notes: str
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class InterviewListResponse(BaseModel):
    total: int
    items: list[InterviewResponse]


class TimeSlot(BaseModel):
    start_time: datetime
    end_time: datetime


class MatchSlotsRequest(BaseModel):
    interviewer_id: int
    candidate_slots: list[CandidateAvailability]
    duration_minutes: int = 60


class MatchSlotsResponse(BaseModel):
    available_slots: list[TimeSlot]
```

**service.py:**
```python
"""日程协调业务逻辑"""
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from app.modules.scheduling.models import Interviewer, InterviewerAvailability, Interview
from app.modules.scheduling.schemas import (
    InterviewerCreate, AvailabilityCreate, InterviewCreate, InterviewUpdate,
    CandidateAvailability, TimeSlot,
)


class SchedulingService:
    def __init__(self, db: Session):
        self.db = db

    # --- 面试官管理 ---
    def create_interviewer(self, data: InterviewerCreate) -> Interviewer:
        interviewer = Interviewer(**data.model_dump())
        self.db.add(interviewer)
        self.db.commit()
        self.db.refresh(interviewer)
        return interviewer

    def get_interviewer(self, interviewer_id: int) -> Interviewer | None:
        return self.db.query(Interviewer).filter(Interviewer.id == interviewer_id).first()

    def list_interviewers(self) -> dict:
        items = self.db.query(Interviewer).all()
        return {"total": len(items), "items": items}

    def delete_interviewer(self, interviewer_id: int) -> bool:
        i = self.get_interviewer(interviewer_id)
        if not i:
            return False
        self.db.delete(i)
        self.db.commit()
        return True

    # --- 面试官可用时间 ---
    def add_availability(self, data: AvailabilityCreate) -> InterviewerAvailability:
        avail = InterviewerAvailability(**data.model_dump())
        self.db.add(avail)
        self.db.commit()
        self.db.refresh(avail)
        return avail

    def get_availability(self, interviewer_id: int) -> list[InterviewerAvailability]:
        return (
            self.db.query(InterviewerAvailability)
            .filter(InterviewerAvailability.interviewer_id == interviewer_id)
            .order_by(InterviewerAvailability.start_time)
            .all()
        )

    # --- 时段匹配 ---
    def match_slots(
        self, interviewer_id: int, candidate_slots: list[CandidateAvailability], duration_minutes: int = 60
    ) -> list[TimeSlot]:
        """匹配面试官与候选人都空闲的时段"""
        interviewer_avails = self.get_availability(interviewer_id)

        # 获取已有面试安排（排除已取消的）
        existing_interviews = (
            self.db.query(Interview)
            .filter(Interview.interviewer_id == interviewer_id, Interview.status != "cancelled")
            .all()
        )

        matched = []
        duration = timedelta(minutes=duration_minutes)

        for i_avail in interviewer_avails:
            for c_slot in candidate_slots:
                # 计算重叠区间
                overlap_start = max(i_avail.start_time, c_slot.start_time)
                overlap_end = min(i_avail.end_time, c_slot.end_time)

                if overlap_end - overlap_start >= duration:
                    # 在重叠区间内按 duration 切分可用时段
                    slot_start = overlap_start
                    while slot_start + duration <= overlap_end:
                        slot_end = slot_start + duration

                        # 检查是否与已有面试冲突
                        has_conflict = False
                        for interview in existing_interviews:
                            if slot_start < interview.end_time and slot_end > interview.start_time:
                                has_conflict = True
                                break

                        if not has_conflict:
                            matched.append(TimeSlot(start_time=slot_start, end_time=slot_end))

                        slot_start += timedelta(minutes=30)  # 每30分钟一个可选时段

        return matched

    # --- 面试安排 ---
    def create_interview(self, data: InterviewCreate) -> Interview | None:
        # 检查冲突
        existing = (
            self.db.query(Interview)
            .filter(
                Interview.interviewer_id == data.interviewer_id,
                Interview.status != "cancelled",
                Interview.start_time < data.end_time,
                Interview.end_time > data.start_time,
            )
            .first()
        )
        if existing:
            return None  # 时间冲突

        interview = Interview(**data.model_dump())
        self.db.add(interview)
        self.db.commit()
        self.db.refresh(interview)
        return interview

    def get_interview(self, interview_id: int) -> Interview | None:
        return self.db.query(Interview).filter(Interview.id == interview_id).first()

    def list_interviews(self, interviewer_id: int | None = None, status: str | None = None) -> dict:
        query = self.db.query(Interview)
        if interviewer_id:
            query = query.filter(Interview.interviewer_id == interviewer_id)
        if status:
            query = query.filter(Interview.status == status)
        items = query.order_by(Interview.start_time).all()
        return {"total": len(items), "items": items}

    def update_interview(self, interview_id: int, data: InterviewUpdate) -> Interview | None:
        interview = self.get_interview(interview_id)
        if not interview:
            return None
        for key, value in data.model_dump(exclude_none=True).items():
            setattr(interview, key, value)
        self.db.commit()
        self.db.refresh(interview)
        return interview

    def cancel_interview(self, interview_id: int) -> Interview | None:
        interview = self.get_interview(interview_id)
        if not interview:
            return None
        interview.status = "cancelled"
        self.db.commit()
        self.db.refresh(interview)
        return interview
```

**test_service.py:**
```python
"""日程协调 service 测试"""
from datetime import datetime, timedelta, timezone
from app.modules.scheduling.service import SchedulingService
from app.modules.scheduling.schemas import (
    InterviewerCreate, AvailabilityCreate, InterviewCreate,
    CandidateAvailability, InterviewUpdate,
)
from app.modules.resume.models import Resume


def _now():
    return datetime.now(timezone.utc).replace(microsecond=0)


def test_create_interviewer(db_session):
    service = SchedulingService(db_session)
    interviewer = service.create_interviewer(InterviewerCreate(
        name="张面试官", email="zhang@company.com", department="技术部",
    ))
    assert interviewer.id is not None
    assert interviewer.name == "张面试官"


def test_list_interviewers(db_session):
    service = SchedulingService(db_session)
    service.create_interviewer(InterviewerCreate(name="面试官A"))
    service.create_interviewer(InterviewerCreate(name="面试官B"))
    result = service.list_interviewers()
    assert result["total"] == 2


def test_add_availability(db_session):
    service = SchedulingService(db_session)
    interviewer = service.create_interviewer(InterviewerCreate(name="面试官"))
    start = _now() + timedelta(hours=1)
    avail = service.add_availability(AvailabilityCreate(
        interviewer_id=interviewer.id,
        start_time=start,
        end_time=start + timedelta(hours=4),
    ))
    assert avail.id is not None

    avails = service.get_availability(interviewer.id)
    assert len(avails) == 1


def test_match_slots(db_session):
    service = SchedulingService(db_session)
    interviewer = service.create_interviewer(InterviewerCreate(name="面试官"))

    base = _now() + timedelta(days=1)
    # 面试官 9:00-12:00 可用
    service.add_availability(AvailabilityCreate(
        interviewer_id=interviewer.id,
        start_time=base.replace(hour=9, minute=0),
        end_time=base.replace(hour=12, minute=0),
    ))

    # 候选人 10:00-14:00 可用
    candidate_slots = [CandidateAvailability(
        start_time=base.replace(hour=10, minute=0),
        end_time=base.replace(hour=14, minute=0),
    )]

    # 匹配1小时时段
    slots = service.match_slots(interviewer.id, candidate_slots, duration_minutes=60)
    # 重叠区间 10:00-12:00，可切出 10:00-11:00, 10:30-11:30, 11:00-12:00
    assert len(slots) == 3
    assert slots[0].start_time.hour == 10


def test_match_slots_with_conflict(db_session):
    service = SchedulingService(db_session)
    interviewer = service.create_interviewer(InterviewerCreate(name="面试官"))

    # 创建简历（面试需要关联简历）
    resume = Resume(name="候选人", phone="10000000001")
    db_session.add(resume)
    db_session.commit()

    base = _now() + timedelta(days=1)
    service.add_availability(AvailabilityCreate(
        interviewer_id=interviewer.id,
        start_time=base.replace(hour=9, minute=0),
        end_time=base.replace(hour=12, minute=0),
    ))

    # 已有面试 10:00-11:00
    service.create_interview(InterviewCreate(
        resume_id=resume.id,
        interviewer_id=interviewer.id,
        start_time=base.replace(hour=10, minute=0),
        end_time=base.replace(hour=11, minute=0),
    ))

    candidate_slots = [CandidateAvailability(
        start_time=base.replace(hour=9, minute=0),
        end_time=base.replace(hour=12, minute=0),
    )]

    slots = service.match_slots(interviewer.id, candidate_slots, duration_minutes=60)
    # 9:00-10:00 OK, 10:00-11:00 冲突, 11:00-12:00 OK
    # 9:00-10:00, 9:30-10:30(冲突), 11:00-12:00
    for slot in slots:
        assert not (slot.start_time.hour == 10 and slot.start_time.minute == 0)


def test_create_interview(db_session):
    service = SchedulingService(db_session)
    interviewer = service.create_interviewer(InterviewerCreate(name="面试官"))
    resume = Resume(name="候选人", phone="10000000099")
    db_session.add(resume)
    db_session.commit()

    base = _now() + timedelta(days=1)
    interview = service.create_interview(InterviewCreate(
        resume_id=resume.id,
        interviewer_id=interviewer.id,
        start_time=base.replace(hour=14, minute=0),
        end_time=base.replace(hour=15, minute=0),
        meeting_link="https://meeting.tencent.com/xxx",
    ))
    assert interview is not None
    assert interview.status == "scheduled"


def test_create_interview_conflict(db_session):
    service = SchedulingService(db_session)
    interviewer = service.create_interviewer(InterviewerCreate(name="面试官"))
    r1 = Resume(name="候选人1", phone="10000000011")
    r2 = Resume(name="候选人2", phone="10000000012")
    db_session.add_all([r1, r2])
    db_session.commit()

    base = _now() + timedelta(days=1)
    service.create_interview(InterviewCreate(
        resume_id=r1.id, interviewer_id=interviewer.id,
        start_time=base.replace(hour=14, minute=0),
        end_time=base.replace(hour=15, minute=0),
    ))

    # 同一时间再安排应返回 None
    result = service.create_interview(InterviewCreate(
        resume_id=r2.id, interviewer_id=interviewer.id,
        start_time=base.replace(hour=14, minute=30),
        end_time=base.replace(hour=15, minute=30),
    ))
    assert result is None


def test_cancel_interview(db_session):
    service = SchedulingService(db_session)
    interviewer = service.create_interviewer(InterviewerCreate(name="面试官"))
    resume = Resume(name="候选人", phone="10000000088")
    db_session.add(resume)
    db_session.commit()

    base = _now() + timedelta(days=1)
    interview = service.create_interview(InterviewCreate(
        resume_id=resume.id, interviewer_id=interviewer.id,
        start_time=base.replace(hour=14, minute=0),
        end_time=base.replace(hour=15, minute=0),
    ))
    cancelled = service.cancel_interview(interview.id)
    assert cancelled.status == "cancelled"
```

**conftest.py update:** Add `import app.modules.scheduling.models  # noqa: F401` before `Base.metadata.create_all`.

Commit: `git commit -m "feat: add scheduling module with interviewer management and time slot matching"`

---

### Task 2: 日程协调 Router

**Files:**
- Create: `app/modules/scheduling/router.py`
- Create: `tests/modules/scheduling/test_router.py`
- Modify: `app/main.py`

**router.py:**
```python
"""日程协调 API 路由"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.scheduling.service import SchedulingService
from app.modules.scheduling.schemas import (
    InterviewerCreate, InterviewerResponse, InterviewerListResponse,
    AvailabilityCreate, AvailabilityResponse,
    InterviewCreate, InterviewUpdate, InterviewResponse, InterviewListResponse,
    MatchSlotsRequest, MatchSlotsResponse,
)

router = APIRouter()


def get_service(db: Session = Depends(get_db)) -> SchedulingService:
    return SchedulingService(db)


# --- 面试官 ---
@router.post("/interviewers", response_model=InterviewerResponse, status_code=201)
def create_interviewer(data: InterviewerCreate, service: SchedulingService = Depends(get_service)):
    return service.create_interviewer(data)


@router.get("/interviewers", response_model=InterviewerListResponse)
def list_interviewers(service: SchedulingService = Depends(get_service)):
    return service.list_interviewers()


@router.delete("/interviewers/{interviewer_id}", status_code=204)
def delete_interviewer(interviewer_id: int, service: SchedulingService = Depends(get_service)):
    if not service.delete_interviewer(interviewer_id):
        raise HTTPException(status_code=404, detail="面试官不存在")


# --- 可用时间 ---
@router.post("/availability", response_model=AvailabilityResponse, status_code=201)
def add_availability(data: AvailabilityCreate, service: SchedulingService = Depends(get_service)):
    return service.add_availability(data)


@router.get("/availability/{interviewer_id}", response_model=list[AvailabilityResponse])
def get_availability(interviewer_id: int, service: SchedulingService = Depends(get_service)):
    return service.get_availability(interviewer_id)


# --- 时段匹配 ---
@router.post("/match-slots", response_model=MatchSlotsResponse)
def match_slots(request: MatchSlotsRequest, service: SchedulingService = Depends(get_service)):
    slots = service.match_slots(request.interviewer_id, request.candidate_slots, request.duration_minutes)
    return {"available_slots": slots}


# --- 面试安排 ---
@router.post("/interviews", response_model=InterviewResponse, status_code=201)
def create_interview(data: InterviewCreate, service: SchedulingService = Depends(get_service)):
    interview = service.create_interview(data)
    if not interview:
        raise HTTPException(status_code=409, detail="面试时间冲突")
    return interview


@router.get("/interviews", response_model=InterviewListResponse)
def list_interviews(
    interviewer_id: int | None = None,
    status: str | None = None,
    service: SchedulingService = Depends(get_service),
):
    return service.list_interviews(interviewer_id=interviewer_id, status=status)


@router.get("/interviews/{interview_id}", response_model=InterviewResponse)
def get_interview(interview_id: int, service: SchedulingService = Depends(get_service)):
    interview = service.get_interview(interview_id)
    if not interview:
        raise HTTPException(status_code=404, detail="面试安排不存在")
    return interview


@router.patch("/interviews/{interview_id}", response_model=InterviewResponse)
def update_interview(interview_id: int, data: InterviewUpdate, service: SchedulingService = Depends(get_service)):
    interview = service.update_interview(interview_id, data)
    if not interview:
        raise HTTPException(status_code=404, detail="面试安排不存在")
    return interview


@router.post("/interviews/{interview_id}/cancel", response_model=InterviewResponse)
def cancel_interview(interview_id: int, service: SchedulingService = Depends(get_service)):
    interview = service.cancel_interview(interview_id)
    if not interview:
        raise HTTPException(status_code=404, detail="面试安排不存在")
    return interview
```

**test_router.py:**
```python
"""日程协调 API 路由测试"""
from datetime import datetime, timedelta, timezone


def _future(hours=24):
    base = datetime.now(timezone.utc) + timedelta(hours=hours)
    return base.replace(microsecond=0).isoformat()


def test_create_interviewer_api(client):
    resp = client.post("/api/scheduling/interviewers", json={"name": "张面试官", "department": "技术部"})
    assert resp.status_code == 201
    assert resp.json()["name"] == "张面试官"


def test_list_interviewers_api(client):
    client.post("/api/scheduling/interviewers", json={"name": "A"})
    client.post("/api/scheduling/interviewers", json={"name": "B"})
    resp = client.get("/api/scheduling/interviewers")
    assert resp.json()["total"] == 2


def test_create_interview_api(client):
    # 创建面试官
    i_resp = client.post("/api/scheduling/interviewers", json={"name": "面试官"})
    iid = i_resp.json()["id"]
    # 创建简历
    r_resp = client.post("/api/resumes/", json={"name": "候选人", "phone": "10000000201"})
    rid = r_resp.json()["id"]

    base = datetime.now(timezone.utc) + timedelta(days=1)
    start = base.replace(hour=14, minute=0, second=0, microsecond=0).isoformat()
    end = base.replace(hour=15, minute=0, second=0, microsecond=0).isoformat()

    resp = client.post("/api/scheduling/interviews", json={
        "resume_id": rid, "interviewer_id": iid,
        "start_time": start, "end_time": end,
        "meeting_link": "https://meeting.tencent.com/test",
    })
    assert resp.status_code == 201
    assert resp.json()["status"] == "scheduled"


def test_cancel_interview_api(client):
    i_resp = client.post("/api/scheduling/interviewers", json={"name": "面试官"})
    r_resp = client.post("/api/resumes/", json={"name": "候选人", "phone": "10000000202"})

    base = datetime.now(timezone.utc) + timedelta(days=2)
    start = base.replace(hour=10, minute=0, second=0, microsecond=0).isoformat()
    end = base.replace(hour=11, minute=0, second=0, microsecond=0).isoformat()

    iv_resp = client.post("/api/scheduling/interviews", json={
        "resume_id": r_resp.json()["id"],
        "interviewer_id": i_resp.json()["id"],
        "start_time": start, "end_time": end,
    })
    iv_id = iv_resp.json()["id"]

    resp = client.post(f"/api/scheduling/interviews/{iv_id}/cancel")
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"
```

Register router in `app/main.py`:
```python
from app.modules.scheduling.router import router as scheduling_router
app.include_router(scheduling_router, prefix="/api/scheduling", tags=["scheduling"])
```

Commit: `git commit -m "feat: add scheduling API routes for interviewers, availability, and interviews"`

---

### Task 3: 会议管理模块

**Files:**
- Create: `app/adapters/tencent_meeting.py`
- Create: `app/modules/meeting/__init__.py`
- Create: `app/modules/meeting/schemas.py`
- Create: `app/modules/meeting/service.py`
- Create: `app/modules/meeting/router.py`
- Create: `tests/modules/meeting/__init__.py`
- Create: `tests/modules/meeting/test_service.py`
- Create: `tests/modules/meeting/test_router.py`
- Modify: `app/main.py`

**tencent_meeting.py:**
```python
"""腾讯会议 API 适配器"""
import hashlib
import hmac
import time
import logging
import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class TencentMeetingAdapter:
    BASE_URL = "https://api.meeting.qq.com/v1"

    def __init__(self):
        self.app_id = settings.tencent_meeting_app_id
        self.secret_id = settings.tencent_meeting_secret_id
        self.secret_key = settings.tencent_meeting_secret_key

    def is_configured(self) -> bool:
        return bool(self.app_id and self.secret_id and self.secret_key)

    def _sign(self, method: str, uri: str, body: str, timestamp: int, nonce: int) -> str:
        to_sign = f"{method}\n{uri}\n{timestamp}\n{nonce}\n{body}\n"
        return hmac.new(
            self.secret_key.encode(), to_sign.encode(), hashlib.sha256
        ).hexdigest()

    async def create_meeting(
        self, topic: str, start_time: str, end_time: str, creator_id: str = "default"
    ) -> dict | None:
        """创建腾讯会议，返回 {link, meeting_id, password} 或 None"""
        if not self.is_configured():
            logger.warning("腾讯会议未配置")
            return None

        ts = int(time.time())
        nonce = ts
        uri = "/v1/meetings"
        body_dict = {
            "instanceid": 1,
            "subject": topic,
            "type": 0,
            "start_time": start_time,
            "end_time": end_time,
            "userid": creator_id,
        }

        import json
        body = json.dumps(body_dict)
        signature = self._sign("POST", uri, body, ts, nonce)

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{self.BASE_URL}/meetings",
                    headers={
                        "Content-Type": "application/json",
                        "X-TC-Key": self.secret_id,
                        "X-TC-Timestamp": str(ts),
                        "X-TC-Nonce": str(nonce),
                        "X-TC-Signature": signature,
                        "AppId": self.app_id,
                    },
                    content=body,
                )
                resp.raise_for_status()
                data = resp.json()
                meeting_info = data.get("meeting_info_list", [{}])[0]
                return {
                    "meeting_id": meeting_info.get("meeting_id", ""),
                    "link": meeting_info.get("join_url", ""),
                    "password": meeting_info.get("password", ""),
                }
        except Exception as e:
            logger.error(f"创建腾讯会议失败: {e}")
            return None
```

**meeting/schemas.py:**
```python
"""会议管理输入/输出"""
from pydantic import BaseModel


class MeetingCreateRequest(BaseModel):
    topic: str
    start_time: str  # ISO format
    end_time: str
    interview_id: int | None = None


class MeetingResponse(BaseModel):
    meeting_id: str
    link: str
    password: str
    status: str  # created, manual, failed


class ManualMeetingRequest(BaseModel):
    interview_id: int
    meeting_link: str
    meeting_password: str = ""
```

**meeting/service.py:**
```python
"""会议管理业务逻辑"""
from sqlalchemy.orm import Session

from app.adapters.tencent_meeting import TencentMeetingAdapter
from app.modules.scheduling.models import Interview


class MeetingService:
    def __init__(self, db: Session, meeting_adapter: TencentMeetingAdapter | None = None):
        self.db = db
        self.adapter = meeting_adapter or TencentMeetingAdapter()

    async def create_meeting(self, topic: str, start_time: str, end_time: str, interview_id: int | None = None) -> dict:
        result = await self.adapter.create_meeting(topic, start_time, end_time)

        if result and interview_id:
            interview = self.db.query(Interview).filter(Interview.id == interview_id).first()
            if interview:
                interview.meeting_link = result["link"]
                interview.meeting_password = result.get("password", "")
                self.db.commit()

        if result:
            return {"meeting_id": result["meeting_id"], "link": result["link"], "password": result.get("password", ""), "status": "created"}
        return {"meeting_id": "", "link": "", "password": "", "status": "failed"}

    def set_manual_meeting(self, interview_id: int, meeting_link: str, meeting_password: str = "") -> bool:
        interview = self.db.query(Interview).filter(Interview.id == interview_id).first()
        if not interview:
            return False
        interview.meeting_link = meeting_link
        interview.meeting_password = meeting_password
        self.db.commit()
        return True
```

**meeting/router.py:**
```python
"""会议管理 API 路由"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.meeting.service import MeetingService
from app.modules.meeting.schemas import MeetingCreateRequest, MeetingResponse, ManualMeetingRequest

router = APIRouter()


def get_service(db: Session = Depends(get_db)) -> MeetingService:
    return MeetingService(db)


@router.post("/create", response_model=MeetingResponse)
async def create_meeting(request: MeetingCreateRequest, service: MeetingService = Depends(get_service)):
    return await service.create_meeting(request.topic, request.start_time, request.end_time, request.interview_id)


@router.post("/manual")
def set_manual_meeting(request: ManualMeetingRequest, service: MeetingService = Depends(get_service)):
    if not service.set_manual_meeting(request.interview_id, request.meeting_link, request.meeting_password):
        raise HTTPException(status_code=404, detail="面试安排不存在")
    return {"status": "ok"}
```

**Tests:**
```python
# test_service.py
"""会议管理 service 测试"""
import pytest
from app.modules.meeting.service import MeetingService
from app.modules.scheduling.models import Interview, Interviewer
from app.modules.resume.models import Resume


class MockMeetingAdapter:
    def is_configured(self):
        return True

    async def create_meeting(self, topic, start_time, end_time, creator_id="default"):
        return {"meeting_id": "mock123", "link": "https://meeting.tencent.com/mock", "password": "1234"}


class FailingMeetingAdapter:
    def is_configured(self):
        return False

    async def create_meeting(self, *args, **kwargs):
        return None


@pytest.mark.asyncio
async def test_create_meeting(db_session):
    service = MeetingService(db_session, meeting_adapter=MockMeetingAdapter())
    result = await service.create_meeting("面试", "2026-04-10T14:00:00", "2026-04-10T15:00:00")
    assert result["status"] == "created"
    assert result["link"] == "https://meeting.tencent.com/mock"


@pytest.mark.asyncio
async def test_create_meeting_failed(db_session):
    service = MeetingService(db_session, meeting_adapter=FailingMeetingAdapter())
    result = await service.create_meeting("面试", "2026-04-10T14:00:00", "2026-04-10T15:00:00")
    assert result["status"] == "failed"


def test_set_manual_meeting(db_session):
    interviewer = Interviewer(name="面试官")
    db_session.add(interviewer)
    resume = Resume(name="候选人", phone="10000000301")
    db_session.add(resume)
    db_session.commit()

    from datetime import datetime, timezone, timedelta
    interview = Interview(
        resume_id=resume.id, interviewer_id=interviewer.id,
        start_time=datetime.now(timezone.utc) + timedelta(days=1),
        end_time=datetime.now(timezone.utc) + timedelta(days=1, hours=1),
    )
    db_session.add(interview)
    db_session.commit()

    service = MeetingService(db_session)
    assert service.set_manual_meeting(interview.id, "https://custom.link", "5678")

    db_session.refresh(interview)
    assert interview.meeting_link == "https://custom.link"
```

```python
# test_router.py
"""会议管理 API 路由测试"""


def test_manual_meeting_not_found(client):
    resp = client.post("/api/meeting/manual", json={
        "interview_id": 99999,
        "meeting_link": "https://test.com",
    })
    assert resp.status_code == 404
```

Register in main.py:
```python
from app.modules.meeting.router import router as meeting_router
app.include_router(meeting_router, prefix="/api/meeting", tags=["meeting"])
```

Commit: `git commit -m "feat: add meeting module with Tencent Meeting adapter and manual fallback"`

---

### Task 4: 通知模块

**Files:**
- Create: `app/adapters/email_sender.py`
- Create: `app/adapters/feishu.py`
- Create: `app/modules/notification/__init__.py`
- Create: `app/modules/notification/models.py`
- Create: `app/modules/notification/schemas.py`
- Create: `app/modules/notification/service.py`
- Create: `app/modules/notification/templates.py`
- Create: `app/modules/notification/router.py`
- Create: `tests/modules/notification/__init__.py`
- Create: `tests/modules/notification/test_service.py`
- Create: `tests/modules/notification/test_router.py`
- Modify: `app/main.py`
- Modify: `tests/conftest.py`

**email_sender.py:**
```python
"""SMTP 邮件发送适配器"""
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from app.config import settings

logger = logging.getLogger(__name__)


class EmailSender:
    def __init__(self):
        self.host = settings.smtp_host
        self.port = settings.smtp_port
        self.user = settings.smtp_user
        self.password = settings.smtp_password
        self.use_ssl = settings.smtp_use_ssl

    def is_configured(self) -> bool:
        return bool(self.host and self.user and self.password)

    def send(self, to: str, subject: str, body: str, html: bool = False) -> bool:
        if not self.is_configured():
            logger.warning("SMTP 未配置，跳过发送")
            return False

        try:
            msg = MIMEMultipart()
            msg["From"] = self.user
            msg["To"] = to
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "html" if html else "plain", "utf-8"))

            if self.use_ssl:
                server = smtplib.SMTP_SSL(self.host, self.port, timeout=30)
            else:
                server = smtplib.SMTP(self.host, self.port, timeout=30)
                server.starttls()

            server.login(self.user, self.password)
            server.send_message(msg)
            server.quit()
            logger.info(f"邮件已发送: {to}")
            return True
        except Exception as e:
            logger.error(f"邮件发送失败 [{to}]: {e}")
            return False
```

**feishu.py:**
```python
"""飞书 API 适配器"""
import logging
import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class FeishuAdapter:
    BASE_URL = "https://open.feishu.cn/open-apis"

    def __init__(self):
        self.app_id = settings.feishu_app_id
        self.app_secret = settings.feishu_app_secret
        self._token = ""

    def is_configured(self) -> bool:
        return bool(self.app_id and self.app_secret)

    async def _get_token(self) -> str:
        if self._token:
            return self._token
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{self.BASE_URL}/auth/v3/tenant_access_token/internal",
                    json={"app_id": self.app_id, "app_secret": self.app_secret},
                )
                self._token = resp.json().get("tenant_access_token", "")
                return self._token
        except Exception as e:
            logger.error(f"获取飞书 token 失败: {e}")
            return ""

    async def send_message(self, user_id: str, content: str, msg_type: str = "text") -> bool:
        if not self.is_configured():
            logger.warning("飞书未配置")
            return False

        token = await self._get_token()
        if not token:
            return False

        try:
            import json
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{self.BASE_URL}/im/v1/messages",
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                    params={"receive_id_type": "user_id"},
                    json={
                        "receive_id": user_id,
                        "msg_type": msg_type,
                        "content": json.dumps({"text": content}) if msg_type == "text" else content,
                    },
                )
                return resp.status_code == 200
        except Exception as e:
            logger.error(f"飞书消息发送失败: {e}")
            return False

    async def get_freebusy(self, user_id: str, start_time: str, end_time: str) -> list[dict]:
        """查询飞书日历忙碌时段"""
        if not self.is_configured():
            return []

        token = await self._get_token()
        if not token:
            return []

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{self.BASE_URL}/calendar/v4/freebusy/list",
                    headers={"Authorization": f"Bearer {token}"},
                    json={
                        "time_min": start_time,
                        "time_max": end_time,
                        "user_id": user_id,
                    },
                )
                data = resp.json()
                return data.get("data", {}).get("freebusy_list", [])
        except Exception as e:
            logger.error(f"查询飞书日历失败: {e}")
            return []
```

**notification/models.py:**
```python
"""通知记录数据模型"""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, DateTime

from app.database import Base


class NotificationLog(Base):
    __tablename__ = "notification_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    interview_id = Column(Integer, nullable=True)
    recipient_type = Column(String(20), nullable=False)  # candidate, interviewer
    recipient_name = Column(String(100), default="")
    channel = Column(String(20), nullable=False)  # email, feishu, template
    recipient_address = Column(String(200), default="")
    subject = Column(String(200), default="")
    content = Column(Text, default="")
    status = Column(String(20), default="sent")  # sent, failed, generated
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
```

**notification/templates.py:**
```python
"""通知消息模板"""


def interview_email_to_candidate(
    candidate_name: str, interviewer_name: str, job_title: str,
    interview_time: str, meeting_link: str, meeting_password: str = "",
) -> tuple[str, str]:
    """生成发给候选人的面试通知邮件，返回 (subject, body)"""
    subject = f"面试邀请 - {job_title}"
    body = f"""尊敬的 {candidate_name}：

您好！感谢您对我们公司的关注。

我们诚挚地邀请您参加以下面试：

- 岗位：{job_title}
- 面试时间：{interview_time}
- 面试官：{interviewer_name}
- 面试方式：线上视频面试
- 会议链接：{meeting_link}
{"- 会议密码：" + meeting_password if meeting_password else ""}

请提前5分钟进入会议室，确保网络通畅、环境安静。

如有任何问题，请随时联系我们。

祝顺利！
"""
    return subject, body


def interview_feishu_to_interviewer(
    interviewer_name: str, candidate_name: str, job_title: str,
    interview_time: str, meeting_link: str, candidate_resume_summary: str = "",
) -> str:
    """生成发给面试官的飞书通知"""
    msg = f"""📋 新面试安排通知

面试官：{interviewer_name}
候选人：{candidate_name}
岗位：{job_title}
时间：{interview_time}
会议链接：{meeting_link}
"""
    if candidate_resume_summary:
        msg += f"\n候选人简介：{candidate_resume_summary}"
    return msg


def interview_template_for_copy(
    candidate_name: str, job_title: str,
    interview_time: str, meeting_link: str, meeting_password: str = "",
) -> str:
    """生成可复制到 Boss直聘/微信 的消息模板"""
    msg = f"""您好 {candidate_name}，我们安排了面试：

岗位：{job_title}
时间：{interview_time}
方式：线上视频面试
会议链接：{meeting_link}
{"会议密码：" + meeting_password if meeting_password else ""}

请提前5分钟入会，祝面试顺利！"""
    return msg
```

**notification/schemas.py:**
```python
"""通知输入/输出数据结构"""
from datetime import datetime
from pydantic import BaseModel


class SendNotificationRequest(BaseModel):
    interview_id: int
    send_email_to_candidate: bool = True
    send_feishu_to_interviewer: bool = True
    generate_template: bool = True


class NotificationResult(BaseModel):
    channel: str
    recipient: str
    status: str
    content: str = ""


class SendNotificationResponse(BaseModel):
    interview_id: int
    results: list[NotificationResult]


class NotificationLogResponse(BaseModel):
    id: int
    interview_id: int | None
    recipient_type: str
    recipient_name: str
    channel: str
    recipient_address: str
    subject: str
    content: str
    status: str
    created_at: datetime
    model_config = {"from_attributes": True}


class NotificationLogListResponse(BaseModel):
    total: int
    items: list[NotificationLogResponse]
```

**notification/service.py:**
```python
"""通知业务逻辑"""
import logging
from sqlalchemy.orm import Session

from app.adapters.email_sender import EmailSender
from app.adapters.feishu import FeishuAdapter
from app.modules.notification.models import NotificationLog
from app.modules.notification.templates import (
    interview_email_to_candidate,
    interview_feishu_to_interviewer,
    interview_template_for_copy,
)
from app.modules.scheduling.models import Interview, Interviewer
from app.modules.resume.models import Resume
from app.modules.screening.models import Job

logger = logging.getLogger(__name__)


class NotificationService:
    def __init__(
        self, db: Session,
        email_sender: EmailSender | None = None,
        feishu_adapter: FeishuAdapter | None = None,
    ):
        self.db = db
        self.email = email_sender or EmailSender()
        self.feishu = feishu_adapter or FeishuAdapter()

    async def send_interview_notifications(
        self, interview_id: int,
        send_email: bool = True, send_feishu: bool = True, generate_template: bool = True,
    ) -> dict:
        interview = self.db.query(Interview).filter(Interview.id == interview_id).first()
        if not interview:
            return {"interview_id": interview_id, "results": []}

        resume = self.db.query(Resume).filter(Resume.id == interview.resume_id).first()
        interviewer = self.db.query(Interviewer).filter(Interviewer.id == interview.interviewer_id).first()
        job = self.db.query(Job).filter(Job.id == interview.job_id).first() if interview.job_id else None

        candidate_name = resume.name if resume else "候选人"
        interviewer_name = interviewer.name if interviewer else "面试官"
        job_title = job.title if job else "面试"
        interview_time = interview.start_time.strftime("%Y-%m-%d %H:%M")
        meeting_link = interview.meeting_link or "待定"
        meeting_password = interview.meeting_password or ""

        results = []

        # 1. 邮件通知候选人
        if send_email and resume and resume.email:
            subject, body = interview_email_to_candidate(
                candidate_name, interviewer_name, job_title,
                interview_time, meeting_link, meeting_password,
            )
            success = self.email.send(resume.email, subject, body)
            status = "sent" if success else "failed"
            self._log(interview_id, "candidate", candidate_name, "email", resume.email, subject, body, status)
            results.append({"channel": "email", "recipient": resume.email, "status": status})

        # 2. 飞书通知面试官
        if send_feishu and interviewer and interviewer.feishu_user_id:
            resume_summary = f"学历：{resume.education}，工作年限：{resume.work_years}年，技能：{resume.skills}" if resume else ""
            msg = interview_feishu_to_interviewer(
                interviewer_name, candidate_name, job_title,
                interview_time, meeting_link, resume_summary,
            )
            success = await self.feishu.send_message(interviewer.feishu_user_id, msg)
            status = "sent" if success else "failed"
            self._log(interview_id, "interviewer", interviewer_name, "feishu", interviewer.feishu_user_id, "面试通知", msg, status)
            results.append({"channel": "feishu", "recipient": interviewer_name, "status": status})

        # 3. 生成消息模板
        if generate_template:
            template = interview_template_for_copy(
                candidate_name, job_title, interview_time, meeting_link, meeting_password,
            )
            self._log(interview_id, "candidate", candidate_name, "template", "", "消息模板", template, "generated")
            results.append({"channel": "template", "recipient": candidate_name, "status": "generated", "content": template})

        return {"interview_id": interview_id, "results": results}

    def list_logs(self, interview_id: int | None = None) -> dict:
        query = self.db.query(NotificationLog)
        if interview_id:
            query = query.filter(NotificationLog.interview_id == interview_id)
        items = query.order_by(NotificationLog.created_at.desc()).all()
        return {"total": len(items), "items": items}

    def _log(self, interview_id, recipient_type, recipient_name, channel, address, subject, content, status):
        log = NotificationLog(
            interview_id=interview_id,
            recipient_type=recipient_type,
            recipient_name=recipient_name,
            channel=channel,
            recipient_address=address,
            subject=subject,
            content=content,
            status=status,
        )
        self.db.add(log)
        self.db.commit()
```

**notification/router.py:**
```python
"""通知 API 路由"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.notification.service import NotificationService
from app.modules.notification.schemas import (
    SendNotificationRequest, SendNotificationResponse,
    NotificationLogListResponse,
)

router = APIRouter()


def get_service(db: Session = Depends(get_db)) -> NotificationService:
    return NotificationService(db)


@router.post("/send", response_model=SendNotificationResponse)
async def send_notifications(request: SendNotificationRequest, service: NotificationService = Depends(get_service)):
    return await service.send_interview_notifications(
        request.interview_id,
        send_email=request.send_email_to_candidate,
        send_feishu=request.send_feishu_to_interviewer,
        generate_template=request.generate_template,
    )


@router.get("/logs", response_model=NotificationLogListResponse)
def list_logs(interview_id: int | None = None, service: NotificationService = Depends(get_service)):
    return service.list_logs(interview_id=interview_id)
```

**Tests:**
```python
# test_service.py
"""通知 service 测试"""
import pytest
from app.modules.notification.service import NotificationService
from app.modules.scheduling.models import Interview, Interviewer
from app.modules.resume.models import Resume
from app.modules.screening.models import Job
from datetime import datetime, timezone, timedelta


class MockEmailSender:
    def __init__(self):
        self.sent = []

    def is_configured(self):
        return True

    def send(self, to, subject, body, html=False):
        self.sent.append({"to": to, "subject": subject})
        return True


class MockFeishuAdapter:
    def __init__(self):
        self.sent = []

    def is_configured(self):
        return True

    async def send_message(self, user_id, content, msg_type="text"):
        self.sent.append({"user_id": user_id, "content": content})
        return True


@pytest.fixture
def notification_deps(db_session):
    interviewer = Interviewer(name="张面试官", feishu_user_id="feishu_123", email="zhang@company.com")
    db_session.add(interviewer)
    resume = Resume(name="李候选人", phone="13800001234", email="li@test.com", education="本科", work_years=3, skills="Python")
    db_session.add(resume)
    job = Job(title="Python开发")
    db_session.add(job)
    db_session.commit()

    base = datetime.now(timezone.utc) + timedelta(days=1)
    interview = Interview(
        resume_id=resume.id, interviewer_id=interviewer.id, job_id=job.id,
        start_time=base.replace(hour=14, minute=0),
        end_time=base.replace(hour=15, minute=0),
        meeting_link="https://meeting.tencent.com/test",
        meeting_password="1234",
    )
    db_session.add(interview)
    db_session.commit()

    return {"interview_id": interview.id}


@pytest.mark.asyncio
async def test_send_all_notifications(db_session, notification_deps):
    email = MockEmailSender()
    feishu = MockFeishuAdapter()
    service = NotificationService(db_session, email_sender=email, feishu_adapter=feishu)

    result = await service.send_interview_notifications(notification_deps["interview_id"])
    assert len(result["results"]) == 3  # email + feishu + template

    # 邮件发送
    assert len(email.sent) == 1
    assert email.sent[0]["to"] == "li@test.com"

    # 飞书通知
    assert len(feishu.sent) == 1
    assert feishu.sent[0]["user_id"] == "feishu_123"

    # 模板生成
    template_result = [r for r in result["results"] if r["channel"] == "template"][0]
    assert "Python开发" in template_result["content"]


@pytest.mark.asyncio
async def test_notification_logs(db_session, notification_deps):
    email = MockEmailSender()
    feishu = MockFeishuAdapter()
    service = NotificationService(db_session, email_sender=email, feishu_adapter=feishu)

    await service.send_interview_notifications(notification_deps["interview_id"])
    logs = service.list_logs(notification_deps["interview_id"])
    assert logs["total"] == 3
```

```python
# test_router.py
"""通知 API 路由测试"""


def test_list_logs_empty(client):
    resp = client.get("/api/notification/logs")
    assert resp.status_code == 200
    assert resp.json()["total"] == 0
```

**conftest.py update:** Add `import app.modules.notification.models  # noqa: F401`

Register in main.py:
```python
from app.modules.notification.router import router as notification_router
app.include_router(notification_router, prefix="/api/notification", tags=["notification"])
```

Commit: `git commit -m "feat: add notification module with email, feishu, and template channels"`

---

### Task 5: 全部测试验证

Run: `python -m pytest tests/ -v --tb=short`
Expected: All tests pass

Verify modules can be imported independently:
```bash
python -c "from app.modules.scheduling.service import SchedulingService; print('Scheduling OK')"
python -c "from app.modules.meeting.service import MeetingService; print('Meeting OK')"
python -c "from app.modules.notification.service import NotificationService; print('Notification OK')"
```

Commit: `git commit -m "chore: plan 3 complete - scheduling, meeting, notification"`
