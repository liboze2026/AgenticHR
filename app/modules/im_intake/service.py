import logging
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.adapters.boss.base import BossAdapter, BossCandidate
from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.im_intake.models import IntakeSlot
from app.modules.im_intake.slot_filler import SlotFiller
from app.modules.im_intake.question_generator import QuestionGenerator
from app.modules.im_intake.pdf_collector import PdfCollector
from app.modules.im_intake.job_matcher import match_job_title
from app.modules.im_intake.decision import decide_next_action, NextAction
from app.modules.im_intake.promote import promote_to_resume
from app.modules.im_intake.templates import HARD_SLOT_KEYS
from app.modules.screening.models import Job

logger = logging.getLogger(__name__)


class IntakeService:
    def __init__(self, db: Session, adapter: BossAdapter, llm,
                 storage_dir: str, hard_max_asks: int = 3, pdf_timeout_hours: int = 72,
                 soft_max_n: int = 3, user_id: int = 0):
        self.db = db
        self.adapter = adapter
        self.llm = llm
        self.filler = SlotFiller(llm=llm)
        self.qg = QuestionGenerator(llm=llm)
        self.pdf = PdfCollector(adapter=adapter, storage_dir=storage_dir, timeout_hours=pdf_timeout_hours)
        self.hard_max_asks = hard_max_asks
        self.pdf_timeout_hours = pdf_timeout_hours
        self.soft_max_n = soft_max_n
        self.user_id = user_id

    def ensure_candidate(self, boss_id: str, name: str = "",
                         job_intention: str | None = None) -> IntakeCandidate:
        c = (self.db.query(IntakeCandidate)
             .filter_by(user_id=self.user_id, boss_id=boss_id)
             .first())
        if c is None:
            job_id = None
            if job_intention:
                jobs = self.db.query(Job).all()
                job_id = match_job_title(
                    job_intention, [{"id": j.id, "title": j.title} for j in jobs], threshold=0.7,
                )
            c = IntakeCandidate(
                user_id=self.user_id,
                boss_id=boss_id, name=name or "", job_intention=job_intention, job_id=job_id,
                intake_status="collecting", source="plugin",
                intake_started_at=datetime.now(timezone.utc),
            )
            self.db.add(c); self.db.commit()
        elif name and not c.name:
            c.name = name; self.db.commit()
        return c

    def ensure_slot_rows(self, candidate_id: int) -> dict[str, IntakeSlot]:
        existing = {s.slot_key: s for s in
                    self.db.query(IntakeSlot).filter_by(candidate_id=candidate_id).all()}
        for k in HARD_SLOT_KEYS:
            if k not in existing:
                s = IntakeSlot(candidate_id=candidate_id, slot_key=k, slot_category="hard")
                self.db.add(s); existing[k] = s
        if "pdf" not in existing:
            s = IntakeSlot(candidate_id=candidate_id, slot_key="pdf", slot_category="pdf")
            self.db.add(s); existing["pdf"] = s
        self.db.commit()
        return existing

    async def analyze_chat(self, candidate: IntakeCandidate,
                           messages: list[dict], job: Job | None) -> NextAction:
        slots_by_key = self.ensure_slot_rows(candidate.id)

        candidate_text = "\n".join(
            m["content"] for m in messages
            if m.get("sender_id") == candidate.boss_id and m.get("content")
        )

        pending_hard = [k for k in HARD_SLOT_KEYS if not slots_by_key[k].value]
        if candidate_text and pending_hard:
            parsed = await self.filler.parse_reply(candidate_text, pending_hard)
            for key, (val, source) in parsed.items():
                s = slots_by_key[key]
                s.value = val if isinstance(val, str) else str(val)
                s.source = source
                s.answered_at = datetime.now(timezone.utc)
            self.db.commit()

        candidate.chat_snapshot = {"messages": messages,
                                   "captured_at": datetime.now(timezone.utc).isoformat()}
        self.db.commit()

        slots = list(slots_by_key.values())
        action = decide_next_action(
            candidate, slots, job, hard_max=self.hard_max_asks, pdf_timeout_h=self.pdf_timeout_hours,
        )

        if action.type == "send_soft":
            dims = action.meta["dimensions"]
            questions = await self.qg.generate_soft(
                dimensions=[{"id": d.get("name"), "name": d.get("name"),
                             "description": d.get("description", "")} for d in dims],
                resume_summary=candidate.raw_text or "",
                max_n=self.soft_max_n,
            )
            if questions:
                action.text = self.qg.pack_soft(questions)
                action.meta["questions"] = questions
            else:
                action = NextAction(type="complete")

        return action

    def record_asked(self, candidate: IntakeCandidate, action: NextAction) -> None:
        by = {s.slot_key: s for s in
              self.db.query(IntakeSlot).filter_by(candidate_id=candidate.id).all()}
        now = datetime.now(timezone.utc)
        if action.type == "send_hard":
            for k in action.meta.get("slot_keys", []):
                by[k].ask_count += 1
                by[k].asked_at = now
                by[k].last_ask_text = action.text
            candidate.intake_status = "awaiting_reply"
        elif action.type == "request_pdf":
            by["pdf"].ask_count += 1
            by["pdf"].asked_at = now
            by["pdf"].last_ask_text = "求简历按钮"
        elif action.type == "send_soft":
            for i, q in enumerate(action.meta.get("questions", []), 1):
                sk = f"soft_q_{i}"
                s = IntakeSlot(
                    candidate_id=candidate.id, slot_key=sk, slot_category="soft",
                    ask_count=1, asked_at=now, last_ask_text=q["question"],
                    question_meta={"dimension_id": q.get("dimension_id"),
                                   "dimension_name": q.get("dimension_name")},
                )
                self.db.add(s)
        self.db.commit()

    def apply_terminal(self, candidate: IntakeCandidate, action: NextAction, user_id: int = 0):
        if action.type == "abandon":
            candidate.intake_status = "abandoned"
            candidate.intake_completed_at = datetime.now(timezone.utc)
            self.db.commit()
            return None
        if action.type == "mark_pending_human":
            candidate.intake_status = "pending_human"
            candidate.intake_completed_at = datetime.now(timezone.utc)
            self.db.commit()
            return None
        if action.type == "complete":
            resume = promote_to_resume(self.db, candidate, user_id=user_id)
            self.db.commit()
            return resume
        return None

    async def process_one(self, boss_candidate: BossCandidate) -> None:
        c = self.ensure_candidate(
            boss_id=boss_candidate.boss_id, name=boss_candidate.name,
            job_intention=boss_candidate.job_intention,
        )
        job = self.db.query(Job).filter_by(id=c.job_id).first() if c.job_id else None
        try:
            msgs = await self.adapter.get_chat_messages(c.boss_id)
            messages = [{"sender_id": m.sender_id, "content": m.content} for m in msgs]
        except Exception as e:
            logger.error(f"get_chat_messages failed [{c.boss_id}]: {e}")
            return

        action = await self.analyze_chat(c, messages, job)
        if action.type in ("send_hard", "send_soft"):
            ok = await self.adapter.send_message(c.boss_id, action.text)
            if ok:
                self.record_asked(c, action)
        elif action.type == "request_pdf":
            try:
                ok = await self.adapter.click_request_resume(c.boss_id)
            except Exception:
                ok = False
            if ok:
                self.record_asked(c, action)
        self.apply_terminal(c, action)
