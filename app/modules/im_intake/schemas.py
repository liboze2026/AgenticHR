from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field


SlotKey = str
SlotCategory = Literal["hard", "pdf", "soft"]
IntakeStatus = Literal["collecting", "awaiting_reply", "pending_human", "complete", "abandoned"]


class SlotOut(BaseModel):
    id: int
    slot_key: SlotKey
    slot_category: SlotCategory
    value: str | None = None
    ask_count: int = 0
    asked_at: datetime | None = None
    answered_at: datetime | None = None
    last_ask_text: str | None = None
    source: str | None = None
    question_meta: dict | None = None


class CandidateOut(BaseModel):
    resume_id: int
    boss_id: str
    name: str
    job_id: int | None = None
    job_title: str = ""
    intake_status: IntakeStatus
    progress_done: int
    progress_total: int
    last_activity_at: datetime | None = None


class CandidateDetailOut(CandidateOut):
    slots: list[SlotOut]


class SlotPatchIn(BaseModel):
    value: str = Field(min_length=1)


class SchedulerStatus(BaseModel):
    running: bool
    next_run_at: datetime | None = None
    daily_cap_used: int
    daily_cap_max: int
    last_batch_size: int
