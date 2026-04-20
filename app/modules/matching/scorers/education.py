"""学历 scorer — 大专/本科/硕士/博士 ordinal 比较."""

_EDU_ORD = {"大专": 1, "本科": 2, "硕士": 3, "博士": 4}


def score_education(resume_education: str, education_requirement: dict) -> float:
    """返回 0-100 分."""
    r = _EDU_ORD.get((resume_education or "").strip(), 0)
    m = _EDU_ORD.get((education_requirement.get("min_level") or "本科").strip(), 2)

    if r >= m:
        return 100.0
    return max(0.0, 100.0 - (m - r) * 40)
