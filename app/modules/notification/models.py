"""通知记录数据模型"""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, DateTime
from app.database import Base


class NotificationLog(Base):
    __tablename__ = "notification_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, default=0, index=True)
    interview_id = Column(Integer, nullable=True)
    recipient_type = Column(String(20), nullable=False)  # candidate, interviewer
    recipient_name = Column(String(100), default="")
    channel = Column(String(20), nullable=False)  # email, feishu, template
    recipient_address = Column(String(200), default="")
    subject = Column(String(200), default="")
    content = Column(Text, default="")
    status = Column(String(20), default="sent")  # sent, failed, generated
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
