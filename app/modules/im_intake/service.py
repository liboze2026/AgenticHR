import logging
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from app.config import settings
from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.im_intake.models import IntakeSlot

# Terminal states must match outbox_service.TERMINAL_CANDIDATE_STATES.
# Duplicated here to avoid circular import (outbox_service imports IntakeService).
TERMINAL_CANDIDATE_STATES = ("complete", "abandoned", "pending_human", "timed_out")
from app.modules.im_intake.slot_filler import SlotFiller
from app.modules.im_intake.question_generator import QuestionGenerator
from app.modules.im_intake.pdf_collector import PdfCollector
from app.modules.im_intake.job_matcher import match_job_title
from app.modules.im_intake.decision import decide_next_action, NextAction
from app.modules.im_intake.promote import promote_to_resume
from app.modules.im_intake.templates import HARD_SLOT_KEYS
from app.modules.screening.models import Job
from app.core.audit.logger import log_event

logger = logging.getLogger(__name__)


def _audit_safe(f_stage: str, action: str, entity_id: int, payload: dict | None = None,
                reviewer_id: int | None = None) -> None:
    """Write an F4 audit event; swallow exceptions so audit never breaks intake flow."""
    try:
        log_event(
            f_stage=f_stage, action=action, entity_type="intake_candidate",
            entity_id=entity_id, input_payload=payload, reviewer_id=reviewer_id,
        )
    except Exception as e:
        logger.warning("audit log_event %s failed: %s", f_stage, e)


class IntakeService:
    def __init__(self, db: Session, adapter=None, llm=None,
                 storage_dir: str = "", hard_max_asks: int = 3, pdf_timeout_hours: int = 72,
                 ask_cooldown_hours: int = 6, soft_max_n: int = 3, user_id: int = 0):
        self.db = db
        self.adapter = adapter
        self.llm = llm
        self.filler = SlotFiller(llm=llm)
        self.qg = QuestionGenerator(llm=llm)
        self.pdf = PdfCollector(adapter=adapter, storage_dir=storage_dir, timeout_hours=pdf_timeout_hours) if adapter else None
        self.hard_max_asks = hard_max_asks
        self.pdf_timeout_hours = pdf_timeout_hours
        self.ask_cooldown_hours = ask_cooldown_hours
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
            now = datetime.now(timezone.utc)
            expires_days = getattr(settings, "f4_expires_days", 14)
            c = IntakeCandidate(
                user_id=self.user_id,
                boss_id=boss_id, name=name or "", job_intention=job_intention, job_id=job_id,
                intake_status="collecting", source="plugin",
                intake_started_at=now,
                expires_at=now + timedelta(days=expires_days),
            )
            self.db.add(c); self.db.commit()
            _audit_safe("f4_candidate_enter", "create", c.id,
                        {"boss_id": boss_id, "job_id": job_id, "name": name},
                        reviewer_id=self.user_id or None)
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

        pending_hard = [k for k in HARD_SLOT_KEYS if not slots_by_key[k].value]
        if messages and pending_hard:
            latest_candidate_msg_at = None
            for m in messages:
                if m.get("sender_id") == candidate.boss_id and m.get("sent_at"):
                    try:
                        ts = datetime.fromisoformat(str(m["sent_at"]).replace("Z", "+00:00"))
                        if latest_candidate_msg_at is None or ts > latest_candidate_msg_at:
                            latest_candidate_msg_at = ts
                    except (ValueError, TypeError):
                        pass

            candidate_msgs = [
                (m.get("sent_at"), (m.get("content") or "").strip())
                for m in messages
                if m.get("sender_id") == candidate.boss_id
            ]

            parsed = await self.filler.parse_conversation(
                messages, candidate.boss_id, pending_hard,
            )
            now = datetime.now(timezone.utc)
            for key, (val, source) in parsed.items():
                s = slots_by_key[key]
                val_str = val if isinstance(val, str) else str(val)
                s.value = val_str
                s.source = source
                s.answered_at = now
                if latest_candidate_msg_at and not s.msg_sent_at:
                    s.msg_sent_at = latest_candidate_msg_at

                phrases = [p.strip() for p in val_str.split(" | ") if p.strip()]
                phrase_ts = []
                for phrase in phrases:
                    matched_at = None
                    for sent_at, content in candidate_msgs:
                        if phrase in content or content in phrase:
                            matched_at = sent_at
                            break
                    phrase_ts.append({"text": phrase, "sent_at": matched_at})
                s.phrase_timestamps = phrase_ts
            self.db.commit()
            _audit_safe("f4_extract_history", "slot_fill", candidate.id,
                        {"filled": list(parsed.keys()), "msg_count": len(messages)},
                        reviewer_id=self.user_id or None)

        # Don't clobber existing chat_snapshot with an empty-messages call —
        # the extension's collect-chat may legitimately pass [] (e.g. just
        # opened the panel before history loaded). Only refresh when we
        # actually have content, OR when there's no snapshot yet.
        if messages or candidate.chat_snapshot is None:
            candidate.chat_snapshot = {
                "messages": messages,
                "captured_at": datetime.now(timezone.utc).isoformat(),
            }
            self.db.commit()

        # Defense-in-depth: if THIS analyze_chat just filled the last unfilled
        # hard slot, any leftover pending/claimed outbox row is now asking a
        # question whose answer is already in. Expire residuals so the outbox
        # poll cannot dispatch a zombie question 30s later. Local import to
        # avoid circular dependency at module load time.
        slots_after = self.db.query(IntakeSlot).filter_by(candidate_id=candidate.id).all()
        slots_by = {s.slot_key: s for s in slots_after}
        all_hard_filled = all(slots_by.get(k) and slots_by[k].value for k in HARD_SLOT_KEYS)
        if all_hard_filled:
            from app.modules.im_intake.outbox_service import expire_pending_for_candidate
            expire_pending_for_candidate(self.db, candidate.id, reason="hard_slots_filled")

        slots = list(slots_by.values())  # use fresh re-query, not stale slots_by_key
        action = decide_next_action(
            candidate, slots, job,
            hard_max=self.hard_max_asks,
            pdf_timeout_h=self.pdf_timeout_hours,
            ask_cooldown_h=self.ask_cooldown_hours,
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
        # Terminal-state guard — a candidate that is already complete/abandoned/
        # pending_human must NEVER be regressed to awaiting_reply by a late
        # ack from a stale outbox row. Bail out silently so the outbox row can
        # still be flipped to "sent" by the caller for audit purposes.
        if candidate.intake_status in TERMINAL_CANDIDATE_STATES:
            return
        by = {s.slot_key: s for s in
              self.db.query(IntakeSlot).filter_by(candidate_id=candidate.id).all()}
        now = datetime.now(timezone.utc)
        if action.type == "send_hard":
            for k in action.meta.get("slot_keys", []):
                slot = by.get(k)
                if slot is None:
                    continue
                # Skip slots that were filled between question scheduling and
                # ack — incrementing ask_count for an answered slot would push
                # the candidate toward hard_max abandonment for no reason.
                if slot.value:
                    continue
                slot.ask_count += 1
                slot.asked_at = now
                slot.last_ask_text = action.text
            candidate.intake_status = "awaiting_reply"
            _audit_safe("f4_question_sent", "send_hard", candidate.id,
                        {"slot_keys": action.meta.get("slot_keys", []), "text": action.text},
                        reviewer_id=self.user_id or None)
        elif action.type == "request_pdf":
            by["pdf"].ask_count += 1
            by["pdf"].asked_at = now
            by["pdf"].last_ask_text = "求简历按钮"
            _audit_safe("f4_pdf_requested", "request_pdf", candidate.id,
                        {"ask_count": by["pdf"].ask_count},
                        reviewer_id=self.user_id or None)
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
            _audit_safe("f4_question_sent", "send_soft", candidate.id,
                        {"question_count": len(action.meta.get("questions", []))},
                        reviewer_id=self.user_id or None)
        self.db.commit()

    def apply_terminal(self, candidate: IntakeCandidate, action: NextAction, user_id: int = 0):
        # Local import to avoid circular dependency (outbox_service imports IntakeService).
        from app.modules.im_intake.outbox_service import expire_pending_for_candidate
        if action.type == "abandon":
            candidate.intake_status = "abandoned"
            candidate.intake_completed_at = datetime.now(timezone.utc)
            self.db.commit()
            expire_pending_for_candidate(self.db, candidate.id, reason="abandon")
            _audit_safe("f4_abandoned", "auto_abandon", candidate.id,
                        {"reason": "pdf_timeout_or_max_asks"}, reviewer_id=user_id or None)
            return None
        if action.type == "mark_pending_human":
            candidate.intake_status = "pending_human"
            candidate.intake_completed_at = datetime.now(timezone.utc)
            self.db.commit()
            expire_pending_for_candidate(self.db, candidate.id, reason="pending_human")
            _audit_safe("f4_pending_human", "auto_mark", candidate.id,
                        {"reason": "hard_max_asks_exhausted"}, reviewer_id=user_id or None)
            return None
        # BUG-013: 移除 timed_out 死分支 —— decide_next_action 从不产生该动作，此分支永远不可达
        # 真正的超时通过 HTTP endpoint POST /candidates/{id}/mark-timed-out 手动触发
        if action.type == "complete":
            resume = promote_to_resume(self.db, candidate, user_id=user_id)
            self.db.commit()
            expire_pending_for_candidate(self.db, candidate.id, reason="complete")
            _audit_safe("f4_completed", "auto_complete", candidate.id,
                        {"promoted_resume_id": getattr(candidate, "promoted_resume_id", None)},
                        reviewer_id=user_id or None)
            return resume
        return None
