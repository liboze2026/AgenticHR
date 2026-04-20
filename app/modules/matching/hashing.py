"""能力模型 + 评分权重的 SHA1 哈希, 用于 matching_result 过时检测."""
import hashlib
import json
from typing import Any


def _canonical_sha1(payload: Any) -> str:
    """dict/list 按 sorted keys 规整化后算 SHA1 hex."""
    if payload is None:
        return ""
    s = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def compute_competency_hash(competency_model: dict) -> str:
    """岗位能力模型 (dict, 通常来自 jobs.competency_model JSON 列) → SHA1 hex."""
    return _canonical_sha1(competency_model or {})


def compute_weights_hash(weights: dict) -> str:
    """评分权重 (dict, 通常来自 ScoringWeights.model_dump()) → SHA1 hex."""
    return _canonical_sha1(weights or {})
