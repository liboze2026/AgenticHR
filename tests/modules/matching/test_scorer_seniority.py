from app.modules.matching.scorers.seniority import score_seniority, match_ordinal


def test_match_ordinal_junior():
    assert match_ordinal("初级工程师") == 1
    assert match_ordinal("junior") == 1


def test_match_ordinal_senior():
    assert match_ordinal("高级工程师") == 3
    assert match_ordinal("Senior Engineer") == 3


def test_match_ordinal_lead():
    assert match_ordinal("技术总监") == 4
    assert match_ordinal("Lead") == 4
    assert match_ordinal("Principal") == 4


def test_match_ordinal_default_mid():
    assert match_ordinal("") == 2
    assert match_ordinal("未知岗位") == 2


def test_equal_level():
    assert score_seniority("高级", "Senior 后端工程师") == 100.0


def test_candidate_higher():
    assert score_seniority("专家", "中级") == 100.0


def test_candidate_one_below():
    assert score_seniority("中级", "高级后端") == 60.0


def test_candidate_two_below():
    assert score_seniority("初级", "专家") == 20.0


def test_empty_seniority_defaults_mid():
    assert score_seniority("", "中级") == 100.0
    assert score_seniority("", "高级") == 60.0
