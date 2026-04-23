import json
import logging
from pathlib import Path
from typing import Any, Protocol

logger = logging.getLogger(__name__)

PROMPT_PARSE = (Path(__file__).parent / "prompts" / "parse_v1.txt").read_text(encoding="utf-8")


class LLMLike(Protocol):
    async def complete(self, messages: list[dict], response_format: str = "json", **kw) -> str: ...


class SlotFiller:
    """LLM-driven slot extractor.

    value = 候选人原话片段合集（直接复制原文，多条 " | " 拼接），不做归一化。
    regex 方案已彻底移除 —— 原因：'明天晚上没空' 里的'明天'会被当作到岗时间，
    '4月25'里的'4月'会被当作'4个月'实习时长，语义完全错乱。
    """

    def __init__(self, llm: LLMLike | None = None):
        self.llm = llm

    async def parse_conversation(
        self,
        messages: list[dict],
        candidate_boss_id: str,
        pending_slot_keys: list[str],
    ) -> dict[str, tuple[Any, str]]:
        """Return {slot_key: (value, source)} for slots that LLM filled (None ones omitted).

        `messages` is the full conversation [{sender_id, content}, ...].
        Messages from `candidate_boss_id` are marked as 候选人; others marked as HR.
        """
        if not messages or not pending_slot_keys or self.llm is None:
            return {}

        lines = []
        for m in messages:
            sender = m.get("sender_id")
            content = (m.get("content") or "").strip()
            if not content:
                continue
            role = "候选人" if sender == candidate_boss_id else "HR"
            lines.append(f"{role}: {content}")
        conversation = "\n".join(lines)

        prompt = PROMPT_PARSE.format(conversation=conversation, pending_keys=pending_slot_keys)
        try:
            raw = await self.llm.complete(
                messages=[{"role": "user", "content": prompt}],
                response_format="json",
                temperature=0.0,
                prompt_version="parse_v2",
                f_stage="f5_intake",
                entity_type="intake_slot",
            )
            data = json.loads(raw)
        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"SlotFiller LLM parse failed: {e}")
            return {}

        result: dict[str, tuple[Any, str]] = {}
        for key in pending_slot_keys:
            v = data.get(key)
            if v in (None, "", []):
                continue
            if isinstance(v, list):
                v = " | ".join(str(x) for x in v if x)
                if not v:
                    continue
            result[key] = (v, "llm")
        return result
