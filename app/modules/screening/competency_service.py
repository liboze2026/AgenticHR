"""能力模型 ↔ 扁平字段的双写逻辑 (F1 过渡期)."""
import logging

from sqlalchemy.orm import sessionmaker

from app.database import engine
from app.modules.screening.models import Job

logger = logging.getLogger(__name__)

_session_factory = sessionmaker(bind=engine)


def apply_competency_to_job(job_id: int, competency_model: dict) -> None:
    """把 competency_model 写入 jobs 表, 同时回填扁平字段.

    映射规则:
      - education.min_level → education_min
      - experience.years_min → work_years_min
      - experience.years_max → work_years_max (null → 99)
      - hard_skills where must_have=True → required_skills (CSV)
    """
    # 防御：拒绝把空 / 残缺的 model 写为 approved（防止 GET 后前端崩溃）
    if not competency_model or not isinstance(competency_model, dict) \
            or not isinstance(competency_model.get("hard_skills"), list):
        raise ValueError(
            f"competency_model is empty or missing hard_skills list; "
            f"refuse to persist as approved. Got: {type(competency_model).__name__}"
        )

    session = _session_factory()
    try:
        job = session.query(Job).filter(Job.id == job_id).first()
        if job is None:
            raise ValueError(f"job {job_id} not found")

        job.competency_model = competency_model
        job.competency_model_status = "approved"

        edu = competency_model.get("education", {}) or {}
        exp = competency_model.get("experience", {}) or {}
        hard = competency_model.get("hard_skills", []) or []

        job.education_min = edu.get("min_level", "") or ""
        job.work_years_min = int(exp.get("years_min") or 0)
        ymax = exp.get("years_max")
        job.work_years_max = int(ymax) if ymax is not None else 99

        required_names = [s["name"] for s in hard if s.get("must_have")]
        job.required_skills = ",".join(required_names)

        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
