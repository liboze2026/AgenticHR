"""面试安排输入/输出数据结构"""
import re
from datetime import datetime
from pydantic import BaseModel, Field, field_validator, model_validator


class InterviewerCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    phone: str = Field(default="", max_length=20)
    email: str = Field(default="", max_length=200)
    department: str = Field(default="")
    feishu_user_id: str = Field(default="")

    @field_validator('phone')
    @classmethod
    def validate_phone(cls, v):
        if v and not re.match(r'^1[3-9]\d{9}$', v):
            raise ValueError('手机号格式不正确，需为11位中国手机号')
        return v

    @field_validator('email')
    @classmethod
    def validate_email(cls, v):
        if v and not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', v):
            raise ValueError('邮箱格式不正确')
        return v

    @model_validator(mode='after')
    def at_least_one_contact(self):
        if not self.phone and not self.email and not self.feishu_user_id:
            raise ValueError('手机号、邮箱、飞书ID至少填写一项')
        return self


class InterviewerResponse(BaseModel):
    id: int
    name: str
    phone: str
    email: str
    department: str
    feishu_user_id: str
    created_at: datetime

    model_config = {"from_attributes": True}


class InterviewerListResponse(BaseModel):
    total: int
    items: list[InterviewerResponse]


class AvailabilityCreate(BaseModel):
    interviewer_id: int
    start_time: datetime
    end_time: datetime
    source: str = Field(default="manual")

    @model_validator(mode='after')
    def validate_time_range(self):
        if self.end_time <= self.start_time:
            raise ValueError('结束时间必须晚于开始时间')
        return self


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


class TimeSlot(BaseModel):
    start_time: datetime
    end_time: datetime


class MatchSlotsRequest(BaseModel):
    interviewer_id: int
    candidate_slots: list[CandidateAvailability]
    duration_minutes: int = Field(default=60, ge=15)


class MatchSlotsResponse(BaseModel):
    available_slots: list[TimeSlot]


class InterviewCreate(BaseModel):
    resume_id: int
    interviewer_id: int
    job_id: int | None = None
    start_time: datetime
    end_time: datetime
    meeting_topic: str = Field(default="", max_length=200)
    meeting_link: str = Field(default="")
    meeting_password: str = Field(default="")
    notes: str = Field(default="")

    @model_validator(mode='after')
    def validate_time_range(self):
        if self.end_time <= self.start_time:
            raise ValueError('结束时间必须晚于开始��间')
        return self


class InterviewUpdate(BaseModel):
    start_time: datetime | None = None
    end_time: datetime | None = None
    meeting_topic: str | None = None
    meeting_link: str | None = None
    meeting_password: str | None = None
    status: str | None = None
    notes: str | None = None

    @model_validator(mode='after')
    def validate_time_range(self):
        if self.start_time is not None and self.end_time is not None:
            if self.end_time <= self.start_time:
                raise ValueError('结束时间必须晚于开始时间')
        return self


class InterviewResponse(BaseModel):
    id: int
    resume_id: int
    interviewer_id: int
    job_id: int | None
    start_time: datetime
    end_time: datetime
    meeting_topic: str
    meeting_link: str
    meeting_password: str
    meeting_account: str
    meeting_id: str
    status: str
    notes: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class InterviewListResponse(BaseModel):
    total: int
    items: list[InterviewResponse]
