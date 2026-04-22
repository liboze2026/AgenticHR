import logging
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.adapters.boss.base import BossAdapter, BossCandidate
from app.modules.im_intake.models import IntakeSlot
from app.modules.im_intake.slot_filler import SlotFiller
from app.modules.im_intake.question_generator import QuestionGenerator
from app.modules.im_intake.pdf_collector import PdfCollector
from app.modules.im_intake.job_matcher import match_job_title
from app.modules.im_intake.templates import HARD_SLOT_KEYS
from app.modules.resume.models import Resume
from app.modules.screening.models import Job

logger = logging.getLogger(__name__)


class IntakeService:
    def __init__(self, db: Session, adapter: BossAdapter, llm,
                 storage_dir: str, hard_max_asks: int = 3, pdf_timeout_hours: int = 72,
                 soft_max_n: int = 3):
        self.db = db
        self.adapter = adapter
        self.llm = llm
        self.filler = SlotFiller(llm=llm)
        self.qg = QuestionGenerator(llm=llm)
        self.pdf = PdfCollector(adapter=adapter, storage_dir=storage_dir, timeout_hours=pdf_timeout_hours)
        self.hard_max_asks = hard_max_asks
        self.soft_max_n = soft_max_n

    async def process_one(self, candidate: BossCandidate) -> None:
        resume, job = self._ensure_resume(candidate)
        if resume is None:
            return
        slots_by_key = self._ensure_slot_rows(resume.id)

        try:
            messages = await self.adapter.get_chat_messages(candidate.boss_id)
        except Exception as e:
            logger.error(f"get_chat_messages failed [{candidate.boss_id}]: {e}")
            return

        candidate_text = "\n".join(m.content for m in messages if m.sender_id == candidate.boss_id)

        pending_hard = [k for k in HARD_SLOT_KEYS if not slots_by_key[k].value]
        if candidate_text and pending_hard:
            parsed = await self.filler.parse_reply(candidate_text, pending_hard)
            for key, (val, source) in parsed.items():
                s = slots_by_key[key]
                s.value = val if isinstance(val, str) else str(val)
                s.source = source
                s.answered_at = datetime.now(timezone.utc)
            self.db.commit()

        pdf_slot = slots_by_key["pdf"]
        if not pdf_slot.value:
            pdf_path, status = await self.pdf.try_collect(candidate.boss_id, pdf_slot)
            if status == "received":
                pdf_slot.value = pdf_path
                pdf_slot.source = "received"
                pdf_slot.answered_at = datetime.now(timezone.utc)
                resume.pdf_path = pdf_path
            elif status == "requested":
                pdf_slot.ask_count += 1
                pdf_slot.asked_at = datetime.now(timezone.utc)
                pdf_slot.last_ask_text = "求简历按钮"
            elif status == "abandon":
                resume.intake_status = "abandoned"
                self.db.commit()
                return
            self.db.commit()

        still_pending_hard = [k for k in HARD_SLOT_KEYS
                              if not slots_by_key[k].value and slots_by_key[k].ask_count < self.hard_max_asks]
        if still_pending_hard:
            packed = self.qg.pack_hard(
                candidate_name=candidate.name,
                job_title=job.title if job else "",
                missing=[(k, slots_by_key[k].ask_count) for k in still_pending_hard],
            )
            ok = await self.adapter.send_message(candidate.boss_id, packed)
            if ok:
                now = datetime.now(timezone.utc)
                for k in still_pending_hard:
                    s = slots_by_key[k]
                    s.ask_count += 1
                    s.asked_at = now
                    s.last_ask_text = packed
                resume.intake_status = "awaiting_reply"
                self.db.commit()

        if pdf_slot.value and resume.raw_text and job and job.competency_model:
            await self._try_send_soft(resume, job, slots_by_key, candidate)

        self._evaluate_completion(resume, slots_by_key)
        self.db.commit()

    def _ensure_resume(self, c: BossCandidate) -> tuple[Resume | None, Job | None]:
        r = self.db.query(Resume).filter_by(boss_id=c.boss_id).first()
        jobs = self.db.query(Job).all()
        job_id = match_job_title(c.job_intention, [{"id": j.id, "title": j.title} for j in jobs], threshold=0.7)
        job = self.db.query(Job).filter_by(id=job_id).first() if job_id else None
        if r is None:
            r = Resume(
                name=c.name, boss_id=c.boss_id, job_id=job_id,
                intake_status="collecting",
                intake_started_at=datetime.now(timezone.utc),
                source="boss_zhipin",
                status="passed",
            )
            self.db.add(r); self.db.commit()
        elif r.job_id is None and job_id:
            r.job_id = job_id
            self.db.commit()
        return r, job

    def _ensure_slot_rows(self, resume_id: int) -> dict[str, IntakeSlot]:
        existing = {s.slot_key: s for s in self.db.query(IntakeSlot).filter_by(resume_id=resume_id).all()}
        for k in HARD_SLOT_KEYS:
            if k not in existing:
                s = IntakeSlot(resume_id=resume_id, slot_key=k, slot_category="hard")
                self.db.add(s); existing[k] = s
        if "pdf" not in existing:
            s = IntakeSlot(resume_id=resume_id, slot_key="pdf", slot_category="pdf")
            self.db.add(s); existing["pdf"] = s
        self.db.commit()
        return existing

    async def _try_send_soft(self, resume: Resume, job: Job, slots: dict, c: BossCandidate) -> None:
        existing_soft = [s for s in slots.values() if s.slot_category == "soft"]
        if existing_soft:
            return
        dims = (job.competency_model or {}).get("assessment_dimensions", [])
        if not dims:
            return
        questions = await self.qg.generate_soft(
            dimensions=[{"id": d.get("name"), "name": d.get("name"), "description": d.get("description", "")}
                        for d in dims],
            resume_summary=resume.raw_text or "",
            max_n=self.soft_max_n,
        )
        if not questions:
            return
        packed = self.qg.pack_soft(questions)
        ok = await self.adapter.send_message(c.boss_id, packed)
        if ok:
            now = datetime.now(timezone.utc)
            for i, q in enumerate(questions):
                s = IntakeSlot(
                    resume_id=resume.id, slot_key=f"soft_q_{i+1}", slot_category="soft",
                    ask_count=1, asked_at=now, last_ask_text=q["question"],
                    question_meta={"dimension_id": q.get("dimension_id"),
                                   "dimension_name": q.get("dimension_name")},
                )
                self.db.add(s); slots[s.slot_key] = s

    def _evaluate_completion(self, r: Resume, slots: dict) -> None:
        hard_filled = all(slots[k].value for k in HARD_SLOT_KEYS)
        hard_exhausted = all(slots[k].value or slots[k].ask_count >= self.hard_max_asks for k in HARD_SLOT_KEYS)
        pdf_done = bool(slots["pdf"].value)

        if hard_filled and pdf_done:
            r.intake_status = "complete"
            r.intake_completed_at = datetime.now(timezone.utc)
        elif hard_exhausted and pdf_done:
            r.intake_status = "pending_human"
            r.intake_completed_at = datetime.now(timezone.utc)
