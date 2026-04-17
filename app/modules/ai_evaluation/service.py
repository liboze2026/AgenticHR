"""AI 简历评估业务逻辑"""
import logging
from sqlalchemy.orm import Session

from app.adapters.ai_provider import AIProvider
from app.modules.resume.models import Resume
from app.modules.screening.models import Job

logger = logging.getLogger(__name__)


class AIEvaluationService:
    def __init__(self, db: Session, ai_provider: AIProvider | None = None):
        self.db = db
        self.ai = ai_provider or AIProvider()

    async def evaluate_single(self, resume_id: int, job_id: int) -> dict:
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

        results.sort(key=lambda x: x.get("score", -1), reverse=True)

        return {
            "job_id": job_id,
            "total": len(resumes),
            "succeeded": succeeded,
            "failed": failed,
            "results": results,
        }
