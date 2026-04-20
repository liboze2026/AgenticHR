"""core.vector.service — cosine + float32 pack."""
import numpy as np
import pytest

from app.core.vector.service import cosine_similarity, pack_vector, unpack_vector, find_nearest


def test_cosine_identical():
    a = [1.0, 0.0, 0.0]
    b = [1.0, 0.0, 0.0]
    assert abs(cosine_similarity(a, b) - 1.0) < 1e-6


def test_cosine_orthogonal():
    a = [1.0, 0.0]
    b = [0.0, 1.0]
    assert abs(cosine_similarity(a, b) - 0.0) < 1e-6


def test_cosine_opposite():
    a = [1.0, 0.0]
    b = [-1.0, 0.0]
    assert abs(cosine_similarity(a, b) - (-1.0)) < 1e-6


def test_pack_unpack_roundtrip():
    vec = [0.1, -0.2, 0.3, 0.4]
    blob = pack_vector(vec)
    assert isinstance(blob, bytes)
    assert len(blob) == 4 * 4
    back = unpack_vector(blob)
    assert len(back) == 4
    for a, b in zip(vec, back):
        assert abs(a - b) < 1e-6


def test_pack_numpy_array():
    vec = np.array([1.0, 2.0, 3.0], dtype=np.float32)
    blob = pack_vector(vec)
    back = unpack_vector(blob)
    assert list(back) == pytest.approx([1.0, 2.0, 3.0])


def test_find_nearest_picks_highest_similarity():
    query = [1.0, 0.0]
    candidates = [
        (1, [0.9, 0.1]),
        (2, [0.1, 0.9]),
        (3, [0.95, 0.05]),
    ]
    best_id, best_sim = find_nearest(query, candidates)
    assert best_id == 3
    assert best_sim > 0.99


def test_find_nearest_empty_returns_none():
    best_id, best_sim = find_nearest([1.0, 0.0], [])
    assert best_id is None
    assert best_sim == 0.0


def test_find_nearest_zero_vector():
    best_id, best_sim = find_nearest([0.0, 0.0], [(1, [1.0, 0.0])])
    assert best_sim == 0.0
