"""Skill matching scorer."""
from unittest.mock import patch
from app.modules.matching.scorers.skill import score_skill


def _hs(name, weight=5, must_have=False, canonical_id=None, level="熟练"):
    return {"name": name, "weight": weight, "must_have": must_have,
            "canonical_id": canonical_id, "level": level}


def test_empty_hard_skills_full_score():
    score, missing = score_skill([], "Python, Go")
    assert score == 100.0
    assert missing == []


def test_canonical_id_exact_match():
    hs = [_hs("Python", canonical_id=1)]
    with patch("app.modules.matching.scorers.skill._lookup_resume_canonicals") as m:
        m.return_value = {1}
        score, missing = score_skill(hs, "Python")
    assert score == 100.0
    assert missing == []


def test_vector_above_075_full_coverage():
    hs = [_hs("Python 开发", canonical_id=None)]
    with patch("app.modules.matching.scorers.skill._lookup_resume_canonicals", return_value=set()), \
         patch("app.modules.matching.scorers.skill._max_vector_similarity", return_value=0.88):
        score, missing = score_skill(hs, "Python")
    assert 85 < score <= 100   # 0.88 乘以权重占比


def test_vector_edge_060_to_075_discounted():
    hs = [_hs("DevOps", canonical_id=None)]
    with patch("app.modules.matching.scorers.skill._lookup_resume_canonicals", return_value=set()), \
         patch("app.modules.matching.scorers.skill._max_vector_similarity", return_value=0.65):
        score, missing = score_skill(hs, "Linux")
    # 0.65 * 0.5 = 0.325 coverage → ~32.5 分
    assert 30 < score < 35


def test_below_060_zero_coverage():
    hs = [_hs("Kubernetes", canonical_id=None)]
    with patch("app.modules.matching.scorers.skill._lookup_resume_canonicals", return_value=set()), \
         patch("app.modules.matching.scorers.skill._max_vector_similarity", return_value=0.40):
        score, missing = score_skill(hs, "Docker")
    assert score == 0.0
    assert missing == []   # must_have=False 不记录 missing


def test_missing_must_have_recorded():
    hs = [_hs("Python", canonical_id=None, must_have=True)]
    with patch("app.modules.matching.scorers.skill._lookup_resume_canonicals", return_value=set()), \
         patch("app.modules.matching.scorers.skill._max_vector_similarity", return_value=0.30):
        score, missing = score_skill(hs, "Java")
    assert score == 0.0
    assert missing == ["Python"]


def test_weighted_aggregation():
    hs = [
        _hs("Python", weight=10, canonical_id=1),   # 匹配 → coverage=1, 权重 10
        _hs("Java", weight=2, canonical_id=2),      # 不匹配 → coverage=0, 权重 2
    ]
    with patch("app.modules.matching.scorers.skill._lookup_resume_canonicals", return_value={1}), \
         patch("app.modules.matching.scorers.skill._max_vector_similarity", return_value=0.0):
        score, _ = score_skill(hs, "Python")
    # (10 * 1.0 + 2 * 0.0) / (10 + 2) * 100 = 83.33
    assert 83 < score < 84
