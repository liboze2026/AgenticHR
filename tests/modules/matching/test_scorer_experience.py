from app.modules.matching.scorers.experience import score_experience


def test_in_range():
    assert score_experience(5, {"years_min": 3, "years_max": 8}) == 100.0


def test_at_lower_bound():
    assert score_experience(3, {"years_min": 3, "years_max": 8}) == 100.0


def test_at_upper_bound():
    assert score_experience(8, {"years_min": 3, "years_max": 8}) == 100.0


def test_under_qualified_linear():
    score = score_experience(2, {"years_min": 4, "years_max": 8})
    assert score == 50.0   # 2/4 * 100


def test_under_qualified_ymin_zero():
    assert score_experience(0, {"years_min": 0, "years_max": 5}) == 100.0


def test_over_qualified_linear():
    score = score_experience(10, {"years_min": 3, "years_max": 5})
    # 过度 5 年 → 100 - 50 = 50, 但最低保 60
    assert score == 60.0


def test_slightly_over_above_60_floor():
    score = score_experience(7, {"years_min": 3, "years_max": 5})
    assert score == 80.0   # 100 - (7-5)*10


def test_ymax_none_defaults_ymin_plus_10():
    score = score_experience(12, {"years_min": 3, "years_max": None})
    # ymax = 13, years 12 在范围内
    assert score == 100.0


def test_over_ymax_none_default():
    score = score_experience(20, {"years_min": 3, "years_max": None})
    # ymax = 13, 过度 7 → 30, 底 60
    assert score == 60.0
