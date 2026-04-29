"""批量重抽未完成候选人 slot 值

适用场景:
  历史候选人 chat_snapshot 已含答案，但当时 collect-chat 未触发或 LLM 失败，
  导致 slot value 为空、ask_count 累计但永远抽不到。
  本脚本对所有 collecting / awaiting_reply 候选人重跑 SlotFiller。
"""
from __future__ import annotations

import asyncio
import sys

import app.modules.resume.models  # noqa: F401
import app.modules.auth.models  # noqa: F401
import app.modules.screening.models  # noqa: F401
import app.modules.scheduling.models  # noqa: F401
import app.modules.notification.models  # noqa: F401
import app.modules.matching.models  # noqa: F401
import app.modules.im_intake.models  # noqa: F401
import app.modules.im_intake.candidate_model  # noqa: F401
import app.modules.im_intake.outbox_model  # noqa: F401
import app.modules.im_intake.settings_model  # noqa: F401
import app.core.audit.models  # noqa: F401

from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.im_intake.models import IntakeSlot
from app.modules.im_intake.slot_filler import SlotFiller
from app.modules.im_intake.templates import HARD_SLOT_KEYS
from app.core.llm.provider import LLMProvider


ACTIVE_STATUSES = ("collecting", "awaiting_reply", "pending_human")


async def reextract_one(db, c: IntakeCandidate, filler: SlotFiller) -> dict:
    msgs = (c.chat_snapshot or {}).get("messages", []) if isinstance(c.chat_snapshot, dict) else []
    if not msgs:
        return {"id": c.id, "skipped": "no_messages"}

    slots = {s.slot_key: s for s in db.query(IntakeSlot).filter_by(candidate_id=c.id).all()}
    pending = [k for k in HARD_SLOT_KEYS if k in slots and not slots[k].value]
    if not pending:
        return {"id": c.id, "skipped": "no_pending"}

    parsed = await filler.parse_conversation(msgs, c.boss_id, pending)
    if not parsed:
        return {"id": c.id, "name": c.name, "filled": []}

    now = datetime.now(timezone.utc)
    filled = []
    for key, (val, source) in parsed.items():
        s = slots[key]
        s.value = val if isinstance(val, str) else str(val)
        s.source = source
        s.answered_at = now
        filled.append(key)
    db.commit()
    return {"id": c.id, "name": c.name, "filled": filled}


async def main():
    e = create_engine("sqlite:///./data/recruitment.db")
    db = sessionmaker(bind=e)()
    llm = LLMProvider()
    if not llm.is_configured():
        print("LLM not configured; aborting.")
        sys.exit(1)
    filler = SlotFiller(llm=llm)

    cands = db.query(IntakeCandidate).filter(
        IntakeCandidate.intake_status.in_(ACTIVE_STATUSES)
    ).all()
    print(f"scanning {len(cands)} candidates ...")

    filled_total = 0
    skipped_total = 0
    for c in cands:
        try:
            r = await reextract_one(db, c, filler)
        except Exception as ex:
            print(f"  #{c.id} ERROR: {ex}")
            continue
        if "skipped" in r:
            skipped_total += 1
        else:
            if r["filled"]:
                print(f"  #{r['id']} {r['name']}: filled {r['filled']}")
                filled_total += len(r["filled"])
    print(f"done. filled {filled_total} slots across candidates; skipped {skipped_total}.")


if __name__ == "__main__":
    asyncio.run(main())
