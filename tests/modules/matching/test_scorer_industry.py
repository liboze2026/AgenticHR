from unittest.mock import patch
from app.modules.matching.scorers.industry import score_industry


def test_empty_industries_full_score():
    assert score_industry("任意工作经历", []) == 100.0


def test_keyword_full_hit():
    assert score_industry("曾在某互联网公司任职 5 年", ["互联网"]) == 100.0


def test_keyword_case_insensitive():
    assert score_industry("worked at a FinTech firm", ["fintech"]) == 100.0


def test_partial_hit():
    # 2 行业要求, 命中 1 个
    score = score_industry("在互联网公司任职", ["互联网", "教育"])
    assert score == 50.0


def test_no_hit_no_vector_fallback():
    with patch("app.modules.matching.scorers.industry._vector_match", return_value=False):
        score = score_industry("在汽车工厂工作", ["金融"])
    assert score == 0.0


def test_vector_fallback_hit():
    with patch("app.modules.matching.scorers.industry._vector_match", return_value=True):
        # 关键词未命中，向量命中 → 算 1 hit
        score = score_industry("曾在教培机构", ["教育"])
    assert score == 100.0


def test_empty_work_experience():
    assert score_industry("", ["互联网"]) == 0.0
