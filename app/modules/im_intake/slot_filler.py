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

    Approach: ask the LLM ONLY to pick which message indices belong to which
    slot, then look up the original message content server-side. The LLM
    never gets to rewrite, summarize, normalize, or invent text — those are
    the failure modes we kept hitting (e.g. '周三晚上8-9不行' getting flipped
    to '周三晚上8-9 可用', or '周五' being hallucinated when the candidate
    only mentioned 周二/周三). Whatever the candidate actually said is what
    shows up in the slot value, byte-for-byte.

    regex 方案早已移除：'明天晚上没空' 里的'明天'会被当作到岗时间，
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
        """Return {slot_key: (value, source)} for slots the LLM populated.

        `messages` is the full conversation [{sender_id, content}, ...].
        We number each non-empty message [#i] so the LLM can refer to it by
        index; we then reconstruct the slot value from the raw `content`.
        """
        if not messages or not pending_slot_keys or self.llm is None:
            return {}

        # Build numbered lines and a parallel index → original-content map.
        # We only retain candidate messages in the lookup table — even if the
        # LLM mistakenly returns an HR-message index, we won't surface HR
        # words as the candidate's quoted slot value.
        lines: list[str] = []
        candidate_msgs: dict[int, str] = {}
        idx = 0
        for m in messages:
            sender = m.get("sender_id")
            content = (m.get("content") or "").strip()
            if not content:
                continue
            role = "候选人" if sender == candidate_boss_id else "HR"
            lines.append(f"[#{idx}] {role}: {content}")
            if role == "候选人":
                candidate_msgs[idx] = content
            idx += 1
        conversation = "\n".join(lines)

        safe_conversation = conversation.replace("{", "{{").replace("}", "}}")
        prompt = PROMPT_PARSE.format(conversation=safe_conversation, pending_keys=pending_slot_keys)
        try:
            raw = await self.llm.complete(
                messages=[{"role": "user", "content": prompt}],
                response_format="json",
                temperature=0.0,
                prompt_version="parse_v3_indices",
                f_stage="intake",
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
            # Accept either a list of ints (new schema) or, defensively, a
            # legacy string (old prompt). For lists, look up the original
            # candidate-message content; preserve the LLM's order so timeline
            # reads naturally.
            if isinstance(v, list):
                quotes: list[str] = []
                for raw_idx in v:
                    try:
                        i = int(raw_idx)
                    except (TypeError, ValueError):
                        continue
                    text = candidate_msgs.get(i)
                    if text and text not in quotes:
                        quotes.append(text)
                if not quotes:
                    continue
                # Newline-joined so multi-line candidate utterances stay
                # readable — '|' delimited squashes them and reads worse.
                joined = "\n".join(quotes)
                result[key] = (joined, "llm")
            elif isinstance(v, str):
                s = v.strip()
                if s:
                    result[key] = (s, "llm")
        return result
