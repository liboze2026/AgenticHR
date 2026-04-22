from datetime import datetime
from app.modules.im_intake.schemas import (
    SlotOut, CandidateOut, CandidateDetailOut, SlotPatchIn,
    SchedulerStatus,
)

def test_slot_out_round_trip():
    s = SlotOut(id=1, slot_key="arrival_date", slot_category="hard",
                value="下周一", ask_count=1, asked_at=datetime(2026,4,22),
                answered_at=datetime(2026,4,22), source="regex",
                last_ask_text="您好~", question_meta=None)
    assert s.slot_key == "arrival_date"

def test_slot_patch_requires_value():
    p = SlotPatchIn(value="下周三")
    assert p.value == "下周三"

def test_scheduler_status_fields():
    s = SchedulerStatus(
        running=True, next_run_at=None,
        daily_cap_used=10, daily_cap_max=1000,
        last_batch_size=5,
    )
    assert s.daily_cap_max == 1000
