"""简历数据模型"""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, Float, DateTime

from app.database import Base


class Resume(Base):
    __tablename__ = "resumes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, default=0, index=True)
    name = Column(String(100), nullable=False, index=True)
    phone = Column(String(20), default="", index=True)
    email = Column(String(200), default="")
    education = Column(String(50), default="")
    bachelor_school = Column(String(200), default="")
    master_school = Column(String(200), default="")
    phd_school = Column(String(200), default="")
    qr_code_path = Column(String(500), default="")
    work_years = Column(Integer, default=0)
    expected_salary_min = Column(Float, default=0)
    expected_salary_max = Column(Float, default=0)
    job_intention = Column(String(200), default="")
    skills = Column(Text, default="")
    work_experience = Column(Text, default="")
    project_experience = Column(Text, default="")
    self_evaluation = Column(Text, default="")
    source = Column(String(50), default="")
    raw_text = Column(Text, default="")
    pdf_path = Column(String(500), default="")
    status = Column(String(20), default="passed")
    ai_parsed = Column(String(10), default="no")  # no, parsing, yes, failed
    ai_score = Column(Float, nullable=True)
    ai_summary = Column(Text, default="")
    reject_reason = Column(String(200), default="")
    seniority = Column(String(20), default="", nullable=False)
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
