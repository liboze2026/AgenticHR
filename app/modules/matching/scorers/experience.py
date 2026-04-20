"""工作经验 scorer — 数值比较."""


def score_experience(resume_work_years: int, experience_requirement: dict) -> float:
    """返回 0-100 分.

    experience_requirement: competency_model['experience'] dict with
        years_min (int), years_max (int | None).
    """
    years = max(0, int(resume_work_years or 0))
    ymin = int(experience_requirement.get("years_min", 0) or 0)
    ymax_raw = experience_requirement.get("years_max")
    ymax = int(ymax_raw) if ymax_raw is not None else (ymin + 10)

    if ymin <= years <= ymax:
        return 100.0
    if years < ymin:
        if ymin == 0:
            return 100.0
        return round(years / ymin * 100.0, 2)
    # years > ymax
    return max(60.0, 100.0 - (years - ymax) * 10)
