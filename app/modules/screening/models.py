"""岗位与筛选规则数据模型"""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, Float, Boolean, DateTime, JSON

from app.database import Base


class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, default=0, index=True)
    title = Column(String(200), nullable=False, index=True)
    department = Column(String(100), default="")
    education_min = Column(String(50), default="")
    work_years_min = Column(Integer, default=0)
    work_years_max = Column(Integer, default=99)
    salary_min = Column(Float, default=0)
    salary_max = Column(Float, default=0)
    required_skills = Column(Text, default="")
    soft_requirements = Column(Text, default="")
    greeting_templates = Column(Text, default="")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    jd_text = Column(Text, default="", nullable=False)
    competency_model = Column(JSON, nullable=True)
    competency_model_status = Column(String(20), default="none", nullable=False)
    scoring_weights = Column(JSON, nullable=True)
    greet_threshold = Column(Integer, default=60, nullable=False)
