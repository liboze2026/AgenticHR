"""F2 触发器 — T1 简历入库 / T2 能力模型发布."""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.config import settings
from app.modules.matching.service import MatchingService
from app.modules.resume.models import Resume
from app.modules.screening.models import Job

logger = logging.getLogger(__name__)


async def on_resume_parsed(db: Session, resume_id: int) -> None:
    """T1: 简历 AI 解析完成 → 对所有 is_active + approved 岗位打分."""
    if not getattr(settings, "matching_enabled", True):
        return
    jobs = db.query(Job).filter(
        Job.is_active == True,
        Job.competency_model_status == "approved",
    ).all()
    service = MatchingService(db)
    for job in jobs:
        try:
            await service.score_pair(resume_id, job.id, triggered_by="T1")
        except Exception as e:
            logger.warning(f"T1 score failed resume={resume_id} job={job.id}: {e}")


async def on_competency_approved(db: Session, job_id: int) -> None:
    """T2: 能力模型发布 → 对过去 N 天入库的 ai_parsed='yes' 简历打分."""
    if not getattr(settings, "matching_enabled", True):
        return
    days = getattr(settings, "matching_trigger_days_back", 90)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    resumes = db.query(Resume).filter(
        Resume.ai_parsed == "yes",
        Resume.created_at >= cutoff,
    ).all()
    service = MatchingService(db)
    for r in resumes:
        try:
            await service.score_pair(r.id, job_id, triggered_by="T2")
        except Exception as e:
            logger.warning(f"T2 score failed resume={r.id} job={job_id}: {e}")
