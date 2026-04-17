"""岗位管理与硬性条件筛选"""
from sqlalchemy.orm import Session

from app.modules.screening.models import Job
from app.modules.screening.schemas import JobCreate, JobUpdate
from app.modules.resume.models import Resume

EDUCATION_LEVELS = {"大专": 1, "本科": 2, "硕士": 3, "博士": 4}


class ScreeningService:
    def __init__(self, db: Session):
        self.db = db

    def create_job(self, data: JobCreate) -> Job:
        job = Job(**data.model_dump())
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)
        return job

    def get_job(self, job_id: int) -> Job | None:
        return self.db.query(Job).filter(Job.id == job_id).first()

    def list_jobs(self, active_only: bool = False, user_id: int | None = None) -> dict:
        query = self.db.query(Job)
        if user_id is not None:
            query = query.filter(Job.user_id == user_id)
        if active_only:
            query = query.filter(Job.is_active == True)
        items = query.order_by(Job.created_at.desc()).all()
        return {"total": len(items), "items": items}

    def update_job(self, job_id: int, data: JobUpdate) -> Job | None:
        job = self.get_job(job_id)
        if not job:
            return None
        for key, value in data.model_dump(exclude_none=True).items():
            setattr(job, key, value)
        self.db.commit()
        self.db.refresh(job)
        return job

    def delete_job(self, job_id: int) -> bool:
        job = self.get_job(job_id)
        if not job:
            return False
        self.db.delete(job)
        self.db.commit()
        return True

    def screen_resumes(self, job_id: int, resume_ids: list[int] | None = None) -> dict:
        job = self.get_job(job_id)
        if not job:
            return {"job_id": job_id, "total": 0, "passed": 0, "rejected": 0, "results": []}

        # 默认候选人都是 passed，筛选对所有未淘汰的候选人生效；
        # 不合格的会被改成 rejected，合格的保持 passed
        query = self.db.query(Resume).filter(Resume.status != "rejected")
        if resume_ids:
            query = query.filter(Resume.id.in_(resume_ids))
        resumes = query.all()

        results = []
        passed_count = 0
        rejected_count = 0

        for resume in resumes:
            reject_reasons = []

            if job.education_min:
                min_level = EDUCATION_LEVELS.get(job.education_min, 0)
                resume_level = EDUCATION_LEVELS.get(resume.education, 0)
                if resume_level < min_level:
                    reject_reasons.append(f"学历不符：要求{job.education_min}，实际{resume.education or '未知'}")

            if resume.work_years < job.work_years_min:
                reject_reasons.append(f"工作年限不足：要求{job.work_years_min}年，实际{resume.work_years}年")
            if resume.work_years > job.work_years_max:
                reject_reasons.append(f"工作年限超出：最高{job.work_years_max}年，实际{resume.work_years}年")

            if job.salary_max > 0 and resume.expected_salary_min > 0:
                if resume.expected_salary_min > job.salary_max:
                    reject_reasons.append(f"薪资期望过高：岗位上限{job.salary_max}，期望{resume.expected_salary_min}")

            if job.required_skills:
                required = [s.strip().lower() for s in job.required_skills.split(",") if s.strip()]
                resume_skills = (resume.skills or "").lower()
                resume_text = (resume.raw_text or "").lower()
                for skill in required:
                    if skill not in resume_skills and skill not in resume_text:
                        reject_reasons.append(f"缺少必备技能：{skill}")

            is_passed = len(reject_reasons) == 0
            if is_passed:
                passed_count += 1
                resume.status = "passed"
            else:
                rejected_count += 1
                resume.status = "rejected"
                resume.reject_reason = "; ".join(reject_reasons)

            results.append({
                "resume_id": resume.id,
                "resume_name": resume.name,
                "passed": is_passed,
                "reject_reasons": reject_reasons,
            })

        self.db.commit()
        return {
            "job_id": job_id,
            "total": len(resumes),
            "passed": passed_count,
            "rejected": rejected_count,
            "results": results,
        }
