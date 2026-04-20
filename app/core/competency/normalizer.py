"""技能归一化: LLM 原名 → skills 表 canonical_id."""
import logging

from app.core.competency import SKILL_SIMILARITY_THRESHOLD
from app.core.competency.skill_library import SkillLibrary, SkillCache
from app.core.vector.service import find_nearest, pack_vector, unpack_vector
from app.core.audit.logger import log_event
from app.core.hitl.service import HitlService
from app.core.llm.provider import LLMProvider

logger = logging.getLogger(__name__)


def get_llm_provider() -> LLMProvider:
    return LLMProvider()


async def normalize_skills(names: list[str], job_id: int) -> list[dict]:
    """返回 [{"name": 原名, "canonical_id": int}, ...]."""
    if not names:
        return []

    llm = get_llm_provider()
    vectors = await llm.embed_batch(names)

    lib = SkillLibrary()
    all_skills = SkillCache.all()
    candidates = []
    for s in all_skills:
        if s["embedding"]:
            candidates.append((s["id"], unpack_vector(s["embedding"])))

    results: list[dict] = []
    for name, vec in zip(names, vectors):
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
        else:
            new_id = lib.insert(
                canonical_name=name,
                source="llm_extracted",
                pending_classification=True,
                embedding=pack_vector(vec),
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
                output_payload={"canonical_id": new_id, "similarity": best_sim, "new": True},
            )
            results.append({"name": name, "canonical_id": new_id})

    return results
