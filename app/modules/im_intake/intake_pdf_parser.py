"""IntakeCandidate PDF 解析与字段填充

接 PDF 后:
  1. 本地 PDF 解析提取 raw_text
  2. regex 抽取 name/phone/email/education
  3. 可选: AI 解析填学校/工作经验等丰富字段
  4. classify_school 算 school_tier
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from sqlalchemy.orm import Session

from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.im_intake.school_tier import classify_school
from app.modules.resume.pdf_parser import (
    extract_resume_fields,
    parse_pdf,
    is_image_pdf,
    ai_parse_resume,
    ai_parse_resume_vision,
)

logger = logging.getLogger(__name__)


def compute_school_tier(candidate: IntakeCandidate) -> str:
    """从最高学历对应学校算 tier；若该学校未识别，回退低一级。

    顺序: 博士 → 硕士 → 本科。第一个匹配到非空 tier 即返回。
    """
    for school in (
        getattr(candidate, "phd_school", "") or "",
        getattr(candidate, "master_school", "") or "",
        getattr(candidate, "bachelor_school", "") or "",
    ):
        if not school:
            continue
        tier = classify_school(school)
        if tier:
            return tier
    return ""


def _is_local_path(path: str) -> bool:
    if not path:
        return False
    low = path.lower()
    if low.startswith(("http://", "https://")):
        return False
    return True


def extract_basic_fields(candidate: IntakeCandidate, db: Session) -> bool:
    """同步抽取基础字段(name/phone/email/education) + raw_text。

    pdf_path 必须是本地路径(URL 跳过)；文件不存在或解析空返回 False。
    """
    if not candidate.pdf_path:
        return False
    if not _is_local_path(candidate.pdf_path):
        logger.info(
            "extract_basic_fields skipped (remote URL): candidate=%s url=%s",
            candidate.id, candidate.pdf_path,
        )
        return False

    raw = parse_pdf(candidate.pdf_path)
    if not raw:
        return False

    candidate.raw_text = raw
    fields = extract_resume_fields(raw)
    if fields.get("phone") and not candidate.phone:
        candidate.phone = fields["phone"]
    if fields.get("email") and not candidate.email:
        candidate.email = fields["email"]
    if fields.get("education") and not candidate.education:
        candidate.education = fields["education"]
    db.flush()
    return True


def _coerce_str(v: Any) -> str:
    return str(v) if isinstance(v, (dict, list)) else (v or "")


async def _ai_parse(candidate: IntakeCandidate, ai_provider) -> dict:
    """根据 PDF 类型选文本或视觉模式 AI 解析。"""
    use_vision = False
    pdf = candidate.pdf_path
    if pdf and os.path.exists(pdf):
        if not candidate.raw_text or len(candidate.raw_text.strip()) < 50 or is_image_pdf(pdf):
            use_vision = True

    if use_vision and pdf:
        return await ai_parse_resume_vision(pdf, ai_provider)
    if candidate.raw_text:
        return await ai_parse_resume(candidate.raw_text, ai_provider)
    return {}


def _apply_ai_fields(candidate: IntakeCandidate, parsed: dict) -> None:
    if not parsed:
        return
    if parsed.get("name") and not candidate.name:
        candidate.name = _coerce_str(parsed["name"])
    if parsed.get("phone") and not candidate.phone:
        candidate.phone = _coerce_str(parsed["phone"])
    if parsed.get("email") and not candidate.email:
        candidate.email = _coerce_str(parsed["email"])
    if parsed.get("education"):
        candidate.education = _coerce_str(parsed["education"])
    if parsed.get("bachelor_school"):
        candidate.bachelor_school = _coerce_str(parsed["bachelor_school"])
    if parsed.get("master_school"):
        candidate.master_school = _coerce_str(parsed["master_school"])
    if parsed.get("phd_school"):
        candidate.phd_school = _coerce_str(parsed["phd_school"])
    if parsed.get("work_years"):
        val = parsed["work_years"]
        candidate.work_years = int(val) if isinstance(val, (int, float)) else 0
    if parsed.get("skills"):
        candidate.skills = _coerce_str(parsed["skills"])
    if parsed.get("work_experience"):
        candidate.work_experience = _coerce_str(parsed["work_experience"])
    if parsed.get("project_experience"):
        candidate.project_experience = _coerce_str(parsed["project_experience"])
    if parsed.get("self_evaluation"):
        candidate.self_evaluation = _coerce_str(parsed["self_evaluation"])
    if parsed.get("job_intention") and not candidate.job_intention:
        candidate.job_intention = _coerce_str(parsed["job_intention"])
    seniority = (parsed.get("seniority") or "").strip()
    if seniority:
        candidate.seniority = seniority
    candidate.ai_parsed = "yes"


def parse_and_fill(
    candidate: IntakeCandidate,
    db: Session,
    ai_provider: Any | None = None,
) -> bool:
    """完整 PDF→字段流程: 同步 regex + 可选 AI + 算 school_tier。

    返回 True 表示至少更新了一个字段。
    """
    if not candidate.pdf_path:
        return False

    updated = extract_basic_fields(candidate, db)

    if ai_provider is not None and getattr(ai_provider, "is_configured", lambda: False)():
        try:
            parsed = asyncio.get_event_loop().run_until_complete(
                _ai_parse(candidate, ai_provider)
            ) if False else asyncio.run(_ai_parse(candidate, ai_provider))
        except RuntimeError:
            # 已有 event loop 时改用任务包装
            parsed = asyncio.get_event_loop().run_until_complete(
                _ai_parse(candidate, ai_provider)
            )
        except Exception as e:
            logger.error(f"AI parse failed for candidate {candidate.id}: {e}")
            parsed = {}

        if parsed:
            _apply_ai_fields(candidate, parsed)
            updated = True

    candidate.school_tier = compute_school_tier(candidate)
    db.flush()
    return updated
