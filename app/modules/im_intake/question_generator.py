import json
from pathlib import Path
from typing import Protocol
from app.modules.im_intake.templates import get_hard_question

PROMPT_SOFT = (Path(__file__).parent / "prompts" / "soft_question_v1.txt").read_text(encoding="utf-8")


class LLMLike(Protocol):
    async def complete(self, messages: list[dict], response_format: str = "json", **kw) -> str: ...


class QuestionGenerator:
    def __init__(self, llm: LLMLike | None = None):
        self.llm = llm

    def pack_hard(self, candidate_name: str, job_title: str, missing: list[tuple[str, int]]) -> str:
        lines = [f"您好{candidate_name}~"]
        if job_title:
            lines.append(f"我们对接的是【{job_title}】岗位，想跟您先确认几个信息：")
        else:
            lines.append("想跟您先确认几个信息：")
        for i, (key, count) in enumerate(missing, 1):
            lines.append(f"{i}. {get_hard_question(key, count)}")
        return "\n".join(lines)

    async def generate_soft(self, dimensions: list[dict], resume_summary: str, max_n: int = 3) -> list[dict]:
        if self.llm is None or not dimensions:
            return []
        prompt = PROMPT_SOFT.format(
            max_n=max_n,
            dimensions=json.dumps(dimensions, ensure_ascii=False),
            resume_summary=resume_summary[:2000],
        )
        try:
            raw = await self.llm.complete(
                messages=[{"role": "user", "content": prompt}],
                response_format="json",
                temperature=0.4,
                prompt_version="soft_question_v1",
            )
            data = json.loads(raw)
            return [d for d in data if d.get("question")][:max_n]
        except Exception:
            return []

    def pack_soft(self, questions: list[dict]) -> str:
        if not questions:
            return ""
        lines = ["想再了解一下："]
        for i, q in enumerate(questions, 1):
            lines.append(f"{i}. {q['question']}")
        return "\n".join(lines)
