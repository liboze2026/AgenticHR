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
    msg_sent_at: datetime | None = None
    phrase_timestamps: list | None = None
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
    promoted_resume_id: int | None = None


class CandidateDetailOut(CandidateOut):
    slots: list[SlotOut]


class SlotPatchIn(BaseModel):
    value: str = Field(min_length=1)


# ---- F3.1 additions ----

class ChatMessageIn(BaseModel):
    sender_id: str
    content: str
    sent_at: str | None = None


class CollectChatIn(BaseModel):
    boss_id: str = Field(min_length=1)
    name: str = ""
    job_intention: str | None = None
    messages: list[ChatMessageIn] = Field(default_factory=list)
    pdf_present: bool = False
    pdf_url: str | None = None


class NextActionOut(BaseModel):
    type: Literal["send_hard", "request_pdf", "wait_pdf", "wait_reply",
                  "send_soft", "complete", "mark_pending_human", "abandon"]
    text: str = ""
    slot_keys: list[str] = Field(default_factory=list)


class CollectChatOut(BaseModel):
    candidate_id: int
    intake_status: str
    next_action: NextActionOut


class AckSentIn(BaseModel):
    action_type: Literal["send_hard", "request_pdf", "send_soft"]
    delivered: bool = True


class StartConversationOut(BaseModel):
    candidate_id: int
    boss_id: str
    deep_link: str


# ---- F4 Task 9: outbox HTTP API schemas ----

class OutboxClaimIn(BaseModel):
    limit: int = Field(default=1, ge=1, le=1)  # hard capped; see outbox_service.claim_batch


class OutboxClaimItem(BaseModel):
    id: int
    candidate_id: int
    boss_id: str
    action_type: str
    text: str
    slot_keys: list = []
    attempts: int


class OutboxClaimOut(BaseModel):
    items: list[OutboxClaimItem]


class OutboxAckIn(BaseModel):
    success: bool
    error: str = ""
