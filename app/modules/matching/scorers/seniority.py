"""职级 scorer — free-text 关键词映射到 1-4 ordinal, 对比打分."""

# 关键词 → ordinal, 顺序从高到低匹配（避免"高级"被"初级"误伤）
_LEVEL_PATTERNS = [
    (("专家", "lead", "主管", "总监", "staff", "principal"), 4),
    (("高级", "senior"), 3),
    (("中级", "mid", "regular"), 2),
    (("初级", "junior", "实习"), 1),
]


def match_ordinal(text: str) -> int:
    """任意职级描述 → 1-4 ordinal. 命中不到时默认 2（中级）."""
    t = (text or "").lower()
    for keywords, ord_ in _LEVEL_PATTERNS:
        if any(k.lower() in t for k in keywords):
            return ord_
    return 2


def score_seniority(resume_seniority: str, competency_job_level: str) -> float:
    """返回 0-100 分.

    resume_seniority: Resume.seniority ('初级'/'中级'/'高级'/'专家'/'').
    competency_job_level: competency_model['job_level'] free text.
    """
    required = match_ordinal(competency_job_level)
    candidate = match_ordinal(resume_seniority)

    diff = candidate - required
    if diff >= 0:
        return 100.0
    if diff == -1:
        return 60.0
    return 20.0
