"""向量打包 / cosine 相似度 / 最近邻检索. 无外部依赖, 仅 numpy."""
import numpy as np
from typing import Sequence


def pack_vector(vec: Sequence[float] | np.ndarray) -> bytes:
    """float[] → bytes (float32 little-endian). 存入 skills.embedding 列."""
    arr = np.asarray(vec, dtype=np.float32)
    return arr.tobytes()


def unpack_vector(blob: bytes) -> np.ndarray:
    """skills.embedding blob → numpy float32 array."""
    return np.frombuffer(blob, dtype=np.float32)


def cosine_similarity(a: Sequence[float] | np.ndarray,
                       b: Sequence[float] | np.ndarray) -> float:
    """两向量余弦. 任一零向量返回 0."""
    a_arr = np.asarray(a, dtype=np.float32)
    b_arr = np.asarray(b, dtype=np.float32)
    na = float(np.linalg.norm(a_arr))
    nb = float(np.linalg.norm(b_arr))
    if na < 1e-12 or nb < 1e-12:
        return 0.0
    return float(np.dot(a_arr, b_arr) / (na * nb))


def find_nearest(
    query: Sequence[float] | np.ndarray,
    candidates: list[tuple[int, Sequence[float] | np.ndarray]],
) -> tuple[int | None, float]:
    """从 (id, vec) 列表里找与 query 余弦最近的一个."""
    if not candidates:
        return None, 0.0

    best_id: int | None = None
    best_sim = -1.0
    for cid, cvec in candidates:
        sim = cosine_similarity(query, cvec)
        if sim > best_sim:
            best_sim = sim
            best_id = cid

    if best_sim < 0:
        return None, 0.0
    return best_id, best_sim
