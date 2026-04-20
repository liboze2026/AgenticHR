"""技能匹配 scorer — canonical_id 精确匹配 + bge-m3 向量相似度两段式."""
import logging
from typing import Any

from app.config import settings
from app.core.vector.service import cosine_similarity, unpack_vector

logger = logging.getLogger(__name__)

_EXACT_THRESHOLD = getattr(settings, "matching_skill_sim_exact", 0.75)
_EDGE_THRESHOLD = getattr(settings, "matching_skill_sim_edge", 0.60)


def _parse_resume_skills(resume_skills_text: str) -> list[str]:
    """'Python, Go, FastAPI' → ['Python', 'Go', 'FastAPI'], 去空"""
    if not resume_skills_text:
        return []
    return [s.strip() for s in resume_skills_text.split(",") if s.strip()]


def _lookup_resume_canonicals(resume_skill_names: list[str], db_session=None) -> set[int]:
    """简历侧技能名 → 技能库 canonical_id 集合. db_session=None 时返回空集合（测试用）."""
    if not db_session or not resume_skill_names:
        return set()
    from sqlalchemy import text
    placeholders = ",".join(":n" + str(i) for i in range(len(resume_skill_names)))
    params = {f"n{i}": n for i, n in enumerate(resume_skill_names)}
    query = text(f"SELECT DISTINCT canonical_id FROM skills WHERE name IN ({placeholders}) AND canonical_id IS NOT NULL")
    try:
        rows = db_session.execute(query, params).fetchall()
        return {r[0] for r in rows if r[0] is not None}
    except Exception as e:
        logger.warning(f"lookup canonicals failed: {e}")
        return set()


def _max_vector_similarity(skill_name: str, resume_skill_names: list[str], db_session=None) -> float:
    """技能名对所有简历侧技能名的最大 cosine. 默认走 skills 表 embedding 列."""
    if not resume_skill_names or not db_session:
        return 0.0
    from sqlalchemy import text
    try:
        row = db_session.execute(
            text("SELECT embedding FROM skills WHERE name = :n LIMIT 1"),
            {"n": skill_name},
        ).fetchone()
        if not row or not row[0]:
            return 0.0
        hs_vec = unpack_vector(row[0])

        best = 0.0
        for rn in resume_skill_names:
            r = db_session.execute(
                text("SELECT embedding FROM skills WHERE name = :n LIMIT 1"),
                {"n": rn},
            ).fetchone()
            if r and r[0]:
                sim = cosine_similarity(hs_vec, unpack_vector(r[0]))
                if sim > best:
                    best = sim
        return best
    except Exception as e:
        logger.warning(f"vector similarity failed for {skill_name}: {e}")
        return 0.0


def score_skill(
    hard_skills: list[dict],
    resume_skills_text: str,
    db_session: Any = None,
) -> tuple[float, list[str]]:
    """返回 (skill_score 0-100, missing_must_haves: list[str]).

    hard_skills: list of dicts from competency_model['hard_skills'], 每个含
                 name/weight/must_have/canonical_id/level.
    resume_skills_text: Resume.skills 列（逗号分隔字符串）.
    db_session: 供 skills 表 canonical_id 和 embedding 查询；None 时降级到纯名字匹配.
    """
    if not hard_skills:
        return 100.0, []

    resume_skill_names = _parse_resume_skills(resume_skills_text)
    resume_canonicals = _lookup_resume_canonicals(resume_skill_names, db_session)

    total_weight = 0
    weighted_coverage = 0.0
    missing_must_haves: list[str] = []

    for hs in hard_skills:
        weight = int(hs.get("weight", 5))
        total_weight += weight

        coverage = 0.0
        cid = hs.get("canonical_id")
        if cid is not None and cid in resume_canonicals:
            coverage = 1.0
        else:
            sim = _max_vector_similarity(hs["name"], resume_skill_names, db_session)
            if sim >= _EXACT_THRESHOLD:
                coverage = sim
            elif sim >= _EDGE_THRESHOLD:
                coverage = sim * 0.5
            else:
                coverage = 0.0
                if hs.get("must_have"):
                    missing_must_haves.append(hs["name"])

        weighted_coverage += weight * coverage

    if total_weight == 0:
        return 100.0, missing_must_haves

    return round(weighted_coverage / total_weight * 100.0, 2), missing_must_haves
