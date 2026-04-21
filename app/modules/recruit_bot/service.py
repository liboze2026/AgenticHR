"""F3 RecruitBot 核心服务 — 候选人 upsert / 决策 / 打招呼记录 / 配额."""
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.modules.resume.models import Resume

if TYPE_CHECKING:
    from app.modules.recruit_bot.schemas import ScrapedCandidate


def _summarize_raw_text(c: "ScrapedCandidate") -> str:
    """拼接所有 scraped 字段为调试 summary."""
    parts = [
        f"姓名:{c.name}",
        f"boss_id:{c.boss_id}",
        f"年龄:{c.age or ''}",
        f"学历:{c.education}",
        f"毕业年:{c.grad_year or ''}",
        f"工作年:{c.work_years}",
        f"学校:{c.school}",
        f"专业:{c.major}",
        f"意向:{c.intended_job}",
        f"技能:{','.join(c.skill_tags)}",
        f"院校tag:{','.join(c.school_tier_tags)}",
        f"排名tag:{','.join(c.ranking_tags)}",
        f"期望薪资:{c.expected_salary}",
        f"活跃:{c.active_status}",
        f"推荐理由:{c.recommendation_reason}",
        f"最近工作:{c.latest_work_brief}",
    ]
    return " | ".join(parts)


def upsert_resume_by_boss_id(
    db: Session, user_id: int, candidate: "ScrapedCandidate",
) -> Resume:
    """按 (user_id, boss_id) 查找或新建 Resume 行.

    已存在时更新非状态字段（保留 status / greet_status / greeted_at / ai_* 不动）.
    """
    existing = (
        db.query(Resume)
        .filter(Resume.user_id == user_id, Resume.boss_id == candidate.boss_id)
        .first()
    )
    now = datetime.now(timezone.utc)
    skills_csv = ",".join(candidate.skill_tags)
    summary = _summarize_raw_text(candidate)
    raw_text = (
        f"{summary} || 原文:{candidate.raw_text}" if candidate.raw_text else summary
    )

    if existing:
        existing.name = candidate.name
        existing.education = candidate.education or existing.education
        existing.work_years = candidate.work_years or existing.work_years
        existing.job_intention = candidate.intended_job or existing.job_intention
        existing.skills = skills_csv or existing.skills
        existing.work_experience = (
            candidate.latest_work_brief or existing.work_experience
        )
        existing.raw_text = raw_text
        existing.updated_at = now
        # 故意不动: status, greet_status, greeted_at, ai_parsed, ai_score, ai_summary
        db.commit()
        db.refresh(existing)
        return existing

    r = Resume(
        user_id=user_id,
        name=candidate.name,
        boss_id=candidate.boss_id,
        education=candidate.education,
        work_years=candidate.work_years,
        job_intention=candidate.intended_job,
        skills=skills_csv,
        work_experience=candidate.latest_work_brief,
        source="boss_zhipin",
        raw_text=raw_text,
        status="passed",
        greet_status="none",
        created_at=now,
        updated_at=now,
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return r
