"""聚合分项得分 + 硬门槛 + 标签派生."""


def aggregate(
    dim_scores: dict,
    missing_must_haves: list[str],
    weights: dict,
) -> dict:
    """返回 {total_score, hard_gate_passed}.

    dim_scores keys: skill/experience/seniority/education/industry.
    weights keys: skill_match/experience/seniority/education/industry. Sum 必须 = 100.
    """
    raw = (
        dim_scores["skill"]      * weights["skill_match"] +
        dim_scores["experience"] * weights["experience"] +
        dim_scores["seniority"]  * weights["seniority"] +
        dim_scores["education"]  * weights["education"] +
        dim_scores["industry"]   * weights["industry"]
    ) / 100.0

    if missing_must_haves:
        total = min(raw * 0.4, 29.0)
        hard_gate_passed = False
    else:
        total = raw
        hard_gate_passed = True

    return {
        "total_score": round(total, 2),
        "hard_gate_passed": hard_gate_passed,
    }


def derive_tags(
    total_score: float,
    hard_gate_passed: bool,
    missing: list[str],
    education_score: float,
    experience_score: float,
) -> list[str]:
    """从分数 + 硬门槛结果派生预设结构化标签."""
    tags: list[str] = []
    if not hard_gate_passed:
        tags.append("硬门槛未过")
        for skill in missing[:3]:
            tags.append(f"必须项缺失-{skill}")
    else:
        if total_score >= 80:
            tags.append("高匹配")
        elif total_score >= 60:
            tags.append("中匹配")
        elif total_score >= 40:
            tags.append("低匹配")
        else:
            tags.append("不匹配")

    if education_score < 50:
        tags.append("学历不达标")
    if experience_score < 50:
        tags.append("经验不足")

    return tags
