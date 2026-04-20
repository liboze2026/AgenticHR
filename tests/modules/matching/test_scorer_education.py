from app.modules.matching.scorers.education import score_education


def test_exact_match():
    assert score_education("本科", {"min_level": "本科"}) == 100.0


def test_over_qualified():
    assert score_education("硕士", {"min_level": "本科"}) == 100.0


def test_one_level_below():
    assert score_education("大专", {"min_level": "本科"}) == 60.0


def test_two_levels_below():
    assert score_education("大专", {"min_level": "硕士"}) == 20.0


def test_three_levels_below():
    # resume 未知学历 (ord=0) 对 min_level 博士 (ord=4) → max(0, 100-4*40) = 0
    assert score_education("", {"min_level": "博士"}) == 0.0


def test_empty_resume_edu():
    # 未知简历学历 (ord=0), min_level 本科 (ord=2) → max(0, 100-80) = 20
    assert score_education("", {"min_level": "本科"}) == 20.0


def test_default_min_level_bachelor():
    assert score_education("硕士", {}) == 100.0   # 默认 min_level=本科
