"""技能归一化: LLM 原名 → skills 表 canonical_id."""
import logging

from app.core.competency import SKILL_SIMILARITY_THRESHOLD
from app.core.competency.skill_library import SkillLibrary, SkillCache
from app.core.vector.service import find_nearest, pack_vector, unpack_vector
from app.core.audit.logger import log_event
from app.core.hitl.service import HitlService
from app.core.llm.provider import LLMProvider, LLMError

logger = logging.getLogger(__name__)


def get_llm_provider() -> LLMProvider:
    return LLMProvider()


async def normalize_skills(names: list[str], job_id: int) -> list[dict]:
    """返回 [{"name": 原名, "canonical_id": int}, ...]."""
    if not names:
        return []

    llm = get_llm_provider()

    # embedding 限流时降级为纯名称匹配，不阻断主流程
    vectors: list | None = None
    try:
        vectors = await llm.embed_batch(names)
    except LLMError as e:
        logger.warning(f"embed_batch failed (rate-limit?), falling back to name-only matching: {e}")

    lib = SkillLibrary()

    if vectors is not None:
        all_skills = SkillCache.all()
        candidates = [(s["id"], unpack_vector(s["embedding"])) for s in all_skills if s["embedding"]]
    else:
        candidates = []

    results: list[dict] = []
    for i, name in enumerate(names):
        vec = vectors[i] if vectors is not None else None

        # 向量相似度匹配（有 embedding 时）
        if vec is not None and candidates:
            best_id, best_sim = find_nearest(vec, candidates)
            if best_id is not None and best_sim > SKILL_SIMILARITY_THRESHOLD:
                existing = lib.find_by_id(best_id)
                if existing and name != existing["canonical_name"]:
                    lib.add_alias_if_absent(existing["canonical_name"], name)
                lib.increment_usage(best_id)
                log_event(
                    f_stage="F1_competency_review",
                    action="normalize",
                    entity_type="skill",
                    entity_id=best_id,
                    input_payload={"name": name, "job_id": job_id},
                    output_payload={"canonical_id": best_id, "similarity": best_sim},
                )
                results.append({"name": name, "canonical_id": best_id})
                continue

        # 名称精确匹配（向量不足或 embedding 降级时）
        name_hit = lib.find_by_name(name)
        if name_hit is not None:
            if vec is not None and not name_hit["embedding"]:
                lib.update_embedding(name_hit["id"], pack_vector(vec))
            lib.increment_usage(name_hit["id"])
            log_event(
                f_stage="F1_competency_review",
                action="normalize",
                entity_type="skill",
                entity_id=name_hit["id"],
                input_payload={"name": name, "job_id": job_id},
                output_payload={"canonical_id": name_hit["id"], "name_match": True},
            )
            results.append({"name": name, "canonical_id": name_hit["id"]})
            continue

        # 新技能，embedding 降级时不存 vector
        new_id = lib.insert(
            canonical_name=name,
            source="llm_extracted",
            pending_classification=True,
            embedding=pack_vector(vec) if vec is not None else None,
        )
        HitlService().create(
            f_stage="F1_skill_classification",
            entity_type="skill",
            entity_id=new_id,
            payload={"name": name, "from_job": job_id},
        )
        log_event(
            f_stage="F1_competency_review",
            action="normalize",
            entity_type="skill",
            entity_id=new_id,
            input_payload={"name": name, "job_id": job_id},
            output_payload={"canonical_id": new_id, "new": True, "embedding_skipped": vec is None},
        )
        results.append({"name": name, "canonical_id": new_id})

    return results
