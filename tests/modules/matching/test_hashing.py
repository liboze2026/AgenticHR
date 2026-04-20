"""Hashing utilities for staleness detection."""
from app.modules.matching.hashing import compute_competency_hash, compute_weights_hash


def test_same_content_same_hash():
    c1 = {"hard_skills": [{"name": "Python", "weight": 8}], "job_level": "senior"}
    c2 = {"job_level": "senior", "hard_skills": [{"name": "Python", "weight": 8}]}
    assert compute_competency_hash(c1) == compute_competency_hash(c2)


def test_content_change_hash_change():
    c1 = {"hard_skills": [{"name": "Python"}]}
    c2 = {"hard_skills": [{"name": "Java"}]}
    assert compute_competency_hash(c1) != compute_competency_hash(c2)


def test_empty_is_stable():
    assert compute_competency_hash({}) == compute_competency_hash({})


def test_weights_hash_shape():
    w = {"skill_match": 35, "experience": 30, "seniority": 15, "education": 10, "industry": 10}
    h = compute_weights_hash(w)
    assert len(h) == 40   # SHA1 hex
    assert compute_weights_hash(w) == compute_weights_hash(w)


def test_weights_change_hash_change():
    w1 = {"skill_match": 35, "experience": 30, "seniority": 15, "education": 10, "industry": 10}
    w2 = {"skill_match": 40, "experience": 25, "seniority": 15, "education": 10, "industry": 10}
    assert compute_weights_hash(w1) != compute_weights_hash(w2)
