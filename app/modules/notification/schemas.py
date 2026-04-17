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
