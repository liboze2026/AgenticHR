from app.modules.matching.scorers.aggregator import aggregate


_WEIGHTS = {"skill_match": 35, "experience": 30, "seniority": 15, "education": 10, "industry": 10}


def test_weighted_sum_no_hard_gate():
    result = aggregate(
        dim_scores={"skill": 80, "experience": 60, "seniority": 70, "education": 100, "industry": 50},
        missing_must_haves=[],
        weights=_WEIGHTS,
    )
    # 80*0.35 + 60*0.30 + 70*0.15 + 100*0.10 + 50*0.10 = 28+18+10.5+10+5 = 71.5
    assert result["total_score"] == 71.5
    assert result["hard_gate_passed"] is True


def test_hard_gate_caps_at_29():
    result = aggregate(
        dim_scores={"skill": 90, "experience": 90, "seniority": 90, "education": 90, "industry": 90},
        missing_must_haves=["Python"],
        weights=_WEIGHTS,
    )
    # raw = 90, * 0.4 = 36, min with 29 → 29
    assert result["total_score"] == 29.0
    assert result["hard_gate_passed"] is False


def test_hard_gate_below_29_preserves():
    result = aggregate(
        dim_scores={"skill": 30, "experience": 30, "seniority": 30, "education": 30, "industry": 30},
        missing_must_haves=["Python"],
        weights=_WEIGHTS,
    )
    # raw = 30, * 0.4 = 12, min(12, 29) = 12
    assert result["total_score"] == 12.0


def test_all_dims_present():
    result = aggregate(
        dim_scores={"skill": 100, "experience": 100, "seniority": 100, "education": 100, "industry": 100},
        missing_must_haves=[],
        weights=_WEIGHTS,
    )
    assert result["total_score"] == 100.0


def test_zero_score():
    result = aggregate(
        dim_scores={"skill": 0, "experience": 0, "seniority": 0, "education": 0, "industry": 0},
        missing_must_haves=[],
        weights=_WEIGHTS,
    )
    assert result["total_score"] == 0.0
