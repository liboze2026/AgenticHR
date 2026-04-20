"""JD → CompetencyModel 抽取."""
import hashlib
import logging
from datetime import datetime, timezone

from pydantic import ValidationError

from app.config import settings
from app.core.audit.logger import log_event
from app.core.competency.normalizer import normalize_skills
from app.core.competency.schema import CompetencyModel
from app.core.llm.parsing import extract_json
from app.core.llm.provider import LLMProvider, LLMError

logger = logging.getLogger(__name__)

PROMPT_VERSION = "f1_competency_v1"
MAX_PARSE_RETRIES = 2

SYSTEM_PROMPT = """你是招聘领域的 HR 专家。给定一段岗位 JD，提取结构化能力模型，严格按 JSON schema 输出。
不要 markdown 包装，不要多余字段。

schema:
{
  "hard_skills": [{"name": str, "level": "了解|熟练|精通",
                   "weight": 1-10, "must_have": bool}],
  "soft_skills": [{"name": str, "weight": 1-10,
                   "assessment_stage": "简历|IM|面试"}],
  "experience": {"years_min": int, "years_max": int|null,
                 "industries": [str], "company_scale": str|null},
  "education": {"min_level": "大专|本科|硕士|博士",
                "preferred_level": str|null, "prestigious_bonus": bool},
  "job_level": str,
  "bonus_items": [str],
  "exclusions": [str],
  "assessment_dimensions": [{"name": str, "description": str,
                             "question_types": [str]}]
}

规则：
1. hard_skills 3–15 条，关键技能 weight 9–10
2. soft_skills 0–8 条
3. assessment_dimensions 2–6 条
4. JD 未提及的字段给空数组 / null，不编造
5. bonus_items = 加分项，exclusions = 淘汰项
"""


class ExtractionFailedError(RuntimeError):
    """抽取失败. 调用方把前端切到扁平字段手填降级路径."""


def get_llm_provider() -> LLMProvider:
    model = settings.ai_model_competency or settings.ai_model
    return LLMProvider(model=model)


async def extract_competency(jd_text: str, job_id: int) -> CompetencyModel:
    """JD → CompetencyModel. 抽取成功后 normalize_skills 补 canonical_id."""
    llm = get_llm_provider()
    jd_hash = hashlib.sha256(jd_text.encode("utf-8")).hexdigest()

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": jd_text},
    ]

    raw: str = ""
    parsed: dict | None = None
    last_err: Exception | None = None

    for attempt in range(1, MAX_PARSE_RETRIES + 1 + 1):
        try:
            raw = await llm.complete(
                messages=messages,
                prompt_version=PROMPT_VERSION,
                f_stage="F1_competency_review",
                entity_type="job",
                entity_id=job_id,
                temperature=0.2,
                response_format="json",
            )
        except LLMError as e:
            last_err = e
            break

        try:
            parsed = extract_json(raw)
            break
        except ValueError as e:
            last_err = e
            logger.warning(f"extract_competency parse attempt {attempt} failed: {e}")
            if attempt <= MAX_PARSE_RETRIES:
                messages = messages + [
                    {"role": "assistant", "content": raw},
                    {"role": "user", "content": "上次输出非合法 JSON. 请严格按 schema 重新输出, 不要任何包装."},
                ]

    if parsed is None:
        log_event(
            f_stage="F1_competency_review",
            action="extract_fail",
            entity_type="job",
            entity_id=job_id,
            input_payload={"jd_hash": jd_hash},
            output_payload={"error": str(last_err)},
            prompt_version=PROMPT_VERSION,
            model_name=llm.model,
        )
        raise ExtractionFailedError(f"LLM extraction failed: {last_err}")

    hard_names = [s["name"] for s in parsed.get("hard_skills", [])]
    norm_results = await normalize_skills(hard_names, job_id=job_id)
    name_to_cid = {r["name"]: r["canonical_id"] for r in norm_results}
    for s in parsed.get("hard_skills", []):
        s["canonical_id"] = name_to_cid.get(s["name"])

    parsed["source_jd_hash"] = jd_hash
    parsed["extracted_at"] = datetime.now(timezone.utc).isoformat()

    try:
        model = CompetencyModel.model_validate(parsed)
    except ValidationError as e:
        log_event(
            f_stage="F1_competency_review",
            action="extract_fail",
            entity_type="job",
            entity_id=job_id,
            input_payload={"jd_hash": jd_hash, "raw_parsed": parsed},
            output_payload={"error": str(e)},
            prompt_version=PROMPT_VERSION,
            model_name=llm.model,
        )
        raise ExtractionFailedError(f"Pydantic validation failed: {e}")

    log_event(
        f_stage="F1_competency_review",
        action="extract",
        entity_type="job",
        entity_id=job_id,
        input_payload={"jd_hash": jd_hash, "jd_length": len(jd_text)},
        output_payload=model.model_dump(mode="json"),
        prompt_version=PROMPT_VERSION,
        model_name=llm.model,
    )
    return model
