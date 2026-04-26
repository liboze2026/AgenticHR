import pytest
from app.modules.im_intake.service import TERMINAL_CANDIDATE_STATES

def test_timed_out_is_terminal():
    assert "timed_out" in TERMINAL_CANDIDATE_STATES

def test_timed_out_in_outbox_service():
    from app.modules.im_intake.outbox_service import TERMINAL_CANDIDATE_STATES as OBS
    assert "timed_out" in OBS
