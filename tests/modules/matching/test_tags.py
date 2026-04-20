from app.modules.matching.scorers.aggregator import derive_tags


def test_high_match_80():
    tags = derive_tags(total_score=80, hard_gate_passed=True, missing=[],
                       education_score=100, experience_score=100)
    assert "高匹配" in tags


def test_mid_match_79():
    tags = derive_tags(total_score=79, hard_gate_passed=True, missing=[],
                       education_score=100, experience_score=100)
    assert "中匹配" in tags
    assert "高匹配" not in tags


def test_low_match_40():
    tags = derive_tags(total_score=40, hard_gate_passed=True, missing=[],
                       education_score=100, experience_score=100)
    assert "低匹配" in tags


def test_no_match_below_40():
    tags = derive_tags(total_score=39, hard_gate_passed=True, missing=[],
                       education_score=100, experience_score=100)
    assert "不匹配" in tags


def test_hard_gate_fail_takes_priority():
    tags = derive_tags(total_score=29, hard_gate_passed=False,
                       missing=["Python"], education_score=100, experience_score=100)
    assert "硬门槛未过" in tags
    assert "必须项缺失-Python" in tags
    assert "不匹配" not in tags
    assert "高匹配" not in tags


def test_missing_must_haves_truncated_to_3():
    tags = derive_tags(
        total_score=29, hard_gate_passed=False,
        missing=["Python", "Go", "Rust", "K8s", "Docker"],
        education_score=100, experience_score=100,
    )
    missing_tags = [t for t in tags if t.startswith("必须项缺失-")]
    assert len(missing_tags) == 3


def test_education_low_adds_tag():
    tags = derive_tags(total_score=70, hard_gate_passed=True, missing=[],
                       education_score=40, experience_score=100)
    assert "学历不达标" in tags


def test_experience_low_adds_tag():
    tags = derive_tags(total_score=70, hard_gate_passed=True, missing=[],
                       education_score=100, experience_score=40)
    assert "经验不足" in tags
