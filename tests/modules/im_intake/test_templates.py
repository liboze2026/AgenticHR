from app.modules.im_intake.templates import HARD_QUESTIONS, get_hard_question

def test_three_keys_three_variants():
    for k in ("arrival_date", "free_slots", "intern_duration"):
        assert k in HARD_QUESTIONS
        assert len(HARD_QUESTIONS[k]) == 3

def test_get_hard_question_by_count():
    q0 = get_hard_question("arrival_date", 0)
    q1 = get_hard_question("arrival_date", 1)
    q2 = get_hard_question("arrival_date", 2)
    assert q0 != q1 != q2
    assert "到岗" in q0 or "入职" in q0

def test_get_hard_question_clamps():
    assert get_hard_question("arrival_date", 99) == get_hard_question("arrival_date", 2)
