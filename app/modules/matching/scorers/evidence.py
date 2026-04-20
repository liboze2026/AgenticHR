"""证据片段生成 — deterministic 定位 + 可选 LLM 文案增强."""
import re
from typing import Any


def _find_offset(pattern: str, text: str) -> tuple[int, int] | None:
    """忽略大小写找首次出现的 (start, end). 找不到返回 None."""
    if not pattern or not text:
        return None
    m = re.search(re.escape(pattern), text, re.IGNORECASE)
    if m:
        return [m.start(), m.end()]
    return None


_SKILL_SOURCES = ["skills", "project_experience", "work_experience", "self_evaluation"]


def _locate_skill(resume: Any, skill: str) -> dict:
    """在简历多个字段里找 skill 首次出现. 找不到返回 offset=None + source='' + 模板文本."""
    for src in _SKILL_SOURCES:
        text = getattr(resume, src, "") or ""
        off = _find_offset(skill, text)
        if off is not None:
            return {"text": f"匹配到 {skill}", "source": src, "offset": off}
    return {"text": f"匹配到 {skill}（简历原文未精确定位）", "source": "", "offset": None}


def build_deterministic_evidence(
    resume: Any,
    matched_skills: list[str],
    experience_range: tuple[int, int],
    matched_industries: list[str],
) -> dict:
    """返回按维度分组的 evidence dict."""
    evidence: dict = {"skill": [], "experience": [], "seniority": [], "education": [], "industry": []}

    for skill in matched_skills:
        evidence["skill"].append(_locate_skill(resume, skill))

    ymin, ymax = experience_range
    years = getattr(resume, "work_years", 0) or 0
    evidence["experience"].append({
        "text": f"工作年限 {years} 年，要求 {ymin}-{ymax} 年",
        "source": "work_years",
        "offset": None,
    })

    seniority = getattr(resume, "seniority", "") or ""
    if seniority:
        evidence["seniority"].append({
            "text": f"职级推断：{seniority}",
            "source": "seniority",
            "offset": None,
        })

    education = getattr(resume, "education", "") or ""
    if education:
        evidence["education"].append({
            "text": f"学历：{education}",
            "source": "education",
            "offset": None,
        })

    for industry in matched_industries:
        work_exp = getattr(resume, "work_experience", "") or ""
        off = _find_offset(industry, work_exp)
        if off is not None:
            evidence["industry"].append({
                "text": f"行业匹配：{industry}",
                "source": "work_experience",
                "offset": off,
            })
        else:
            evidence["industry"].append({
                "text": f"行业匹配：{industry}（未精确定位）",
                "source": "",
                "offset": None,
            })

    return evidence
