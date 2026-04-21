"""F3 RecruitBot 核心服务 — 候选人 upsert / 决策 / 打招呼记录 / 配额."""
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.modules.resume.models import Resume

if TYPE_CHECKING:
    from app.modules.recruit_bot.schemas import ScrapedCandidate


def _safe_csv(tags: list[str]) -> str:
    """Join tags into a CSV; strip embedded commas from each tag so downstream
    ``str.split(',')`` consumers don't get split mid-tag (e.g. a tag
    ``"C++, Java"`` would otherwise corrupt the skills column)."""
    return ",".join(t.replace(",", " ") for t in tags)


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
        f"技能:{_safe_csv(c.skill_tags)}",
        f"院校tag:{_safe_csv(c.school_tier_tags)}",
        f"排名tag:{_safe_csv(c.ranking_tags)}",
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

    **Empty-string semantic:** ``candidate.education == ""``, ``work_years == 0`` 等
    在 update 分支视为 "scraper 本次未观察到该字段, 保留既有值". 这是 Boss 页面
    DOM 抓取的自然模式 (缺字段 → 空默认), 避免页面偶发渲染失败把已有值清空.
    如需主动清字段, 不得走 upsert — 必须 DELETE+INSERT 或单独的 dedicated
    endpoint. 在 ``ScrapedCandidate`` schema 迁移为 None-sentinel 之前, 保留此
    语义; 任何语义变更应当作独立任务, 不能在 T2 范围内改.
    """
    existing = (
        db.query(Resume)
        .filter(Resume.user_id == user_id, Resume.boss_id == candidate.boss_id)
        .first()
    )
    now = datetime.now(timezone.utc)
    skills_csv = _safe_csv(candidate.skill_tags)
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


import logging
from app.core.audit.logger import log_event
from app.modules.auth.models import User
from app.modules.recruit_bot.schemas import RecruitDecision, UsageInfo
from app.modules.screening.models import Job
from app.modules.matching.service import MatchingService

logger = logging.getLogger(__name__)


def _today_start_utc() -> datetime:
    """当日 UTC 零点 (配额窗口起点)."""
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def get_daily_usage(db: Session, user_id: int) -> UsageInfo:
    """返该 user 今日已打招呼次数 + 配额."""
    user = db.query(User).filter(User.id == user_id).first()
    cap = user.daily_cap if user else 1000
    start = _today_start_utc()
    used = (
        db.query(Resume)
        .filter(
            Resume.user_id == user_id,
            Resume.greet_status == "greeted",
            Resume.greeted_at >= start,
        )
        .count()
    )
    return UsageInfo(used=used, cap=cap, remaining=max(0, cap - used))


async def evaluate_and_record(
    db: Session, user_id: int, job_id: int,
    candidate: "ScrapedCandidate",
) -> RecruitDecision:
    """核心决策: daily_cap → upsert → 已 greeted skip → F2 score → threshold → record."""
    # 1. daily_cap 先于一切 (省打分钱, 也避免无意义 upsert)
    usage = get_daily_usage(db, user_id)
    if usage.remaining <= 0:
        log_event(
            f_stage="F3_evaluate", action="blocked_daily_cap",
            entity_type="job", entity_id=job_id,
            input_payload={"boss_id": candidate.boss_id, "usage": usage.model_dump()},
            reviewer_id=user_id,
        )
        return RecruitDecision(
            decision="blocked_daily_cap",
            reason=f"今日已打 {usage.used}/{usage.cap}",
        )

    # 2. job 归属 + competency_model
    job = (
        db.query(Job)
        .filter(Job.id == job_id, Job.user_id == user_id)
        .first()
    )
    if not job:
        raise ValueError(f"job {job_id} not found for user {user_id}")
    if not job.competency_model:
        log_event(
            f_stage="F3_evaluate", action="error_no_competency",
            entity_type="job", entity_id=job_id,
            input_payload={"boss_id": candidate.boss_id},
            reviewer_id=user_id,
        )
        return RecruitDecision(
            decision="error_no_competency",
            reason=f"job {job_id} 能力模型未生成",
        )

    # 3. upsert resume
    resume = upsert_resume_by_boss_id(db, user_id=user_id, candidate=candidate)

    # 4. 已 greeted 跳过 (历史覆盖, 不重复打招呼)
    if resume.greet_status == "greeted":
        log_event(
            f_stage="F3_evaluate", action="skipped_already_greeted",
            entity_type="resume", entity_id=resume.id,
            input_payload={"boss_id": candidate.boss_id},
            reviewer_id=user_id,
        )
        return RecruitDecision(
            decision="skipped_already_greeted",
            resume_id=resume.id,
            reason="历史已打过招呼",
        )

    # 5. F2 匹配打分
    svc = MatchingService(db)
    try:
        result = await svc.score_pair(resume.id, job.id, triggered_by="F3")
    except Exception as e:
        logger.exception(f"F3 score_pair failed: {e}")
        log_event(
            f_stage="F3_evaluate", action="error_scoring",
            entity_type="resume", entity_id=resume.id,
            input_payload={"boss_id": candidate.boss_id},
            output_payload={"error": str(e)},
            reviewer_id=user_id,
        )
        return RecruitDecision(
            decision="error_scoring",
            resume_id=resume.id,
            reason=f"打分异常: {e}",
        )

    threshold = job.greet_threshold
    score = int(result.total_score)

    # 6. 阈值判定 + 更新 resume
    if score >= threshold:
        resume.status = "passed"
        resume.greet_status = "pending_greet"
        db.commit()
        log_event(
            f_stage="F3_evaluate", action="should_greet",
            entity_type="resume", entity_id=resume.id,
            input_payload={"boss_id": candidate.boss_id, "score": score, "threshold": threshold},
            reviewer_id=user_id,
        )
        return RecruitDecision(
            decision="should_greet",
            resume_id=resume.id, score=score, threshold=threshold,
            reason=f"分 {score} ≥ 阈值 {threshold}",
        )
    else:
        resume.status = "rejected"
        resume.reject_reason = f"F3 分{score}低于阈值{threshold}"
        db.commit()
        log_event(
            f_stage="F3_evaluate", action="rejected_low_score",
            entity_type="resume", entity_id=resume.id,
            input_payload={"boss_id": candidate.boss_id, "score": score, "threshold": threshold},
            reviewer_id=user_id,
        )
        return RecruitDecision(
            decision="rejected_low_score",
            resume_id=resume.id, score=score, threshold=threshold,
            reason=f"分 {score} < 阈值 {threshold}",
        )
