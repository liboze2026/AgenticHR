from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Literal, Any
from app.modules.im_intake.templates import HARD_SLOT_KEYS
from app.modules.im_intake.question_generator import QuestionGenerator

ActionType = Literal[
    "send_hard", "request_pdf", "wait_pdf",
    "send_soft", "complete", "mark_pending_human", "abandon",
]


@dataclass
class NextAction:
    type: ActionType
    text: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


def _slots_by_key(slots):
    return {s.slot_key: s for s in slots}


def decide_next_action(candidate, slots, job, hard_max: int = 3, pdf_timeout_h: int = 72) -> NextAction:
    by = _slots_by_key(slots)
    pdf = by.get("pdf")

    if pdf and not pdf.value and pdf.asked_at:
        asked = pdf.asked_at if pdf.asked_at.tzinfo else pdf.asked_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - asked > timedelta(hours=pdf_timeout_h):
            return NextAction(type="abandon")

    pending = [k for k in HARD_SLOT_KEYS
               if k in by and not by[k].value and by[k].ask_count < hard_max]
    if pending:
        qg = QuestionGenerator(llm=None)
        missing = [(k, by[k].ask_count) for k in pending]
        text = qg.pack_hard(
            candidate_name=getattr(candidate, "name", ""),
            job_title=getattr(job, "title", "") if job else "",
            missing=missing,
        )
        return NextAction(type="send_hard", text=text, meta={"slot_keys": pending})

    if pdf and not pdf.value:
        if pdf.ask_count == 0:
            return NextAction(type="request_pdf")
        return NextAction(type="wait_pdf")

    hard_filled = all(by[k].value for k in HARD_SLOT_KEYS if k in by)
    if not hard_filled:
        return NextAction(type="mark_pending_human")

    soft_sent = any(s.slot_category == "soft" for s in slots)
    dims = (getattr(job, "competency_model", None) or {}).get("assessment_dimensions") if job else None
    if dims and not soft_sent:
        return NextAction(type="send_soft", meta={"dimensions": dims})

    return NextAction(type="complete")
