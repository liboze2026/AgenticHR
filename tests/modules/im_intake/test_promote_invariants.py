"""spec 0429 阶段 C — promote_to_resume 1:1 不变量与孤儿检测

阶段 C 加 unique index + Resume.intake_candidate_id 反向键后必须满足：
  - 一个 Resume 最多被一个 IntakeCandidate.promoted_resume_id 指
  - Resume.intake_candidate_id 反向唯一指回 candidate
  - sanity check 脚本能识别脏数据
"""
import pytest
from sqlalchemy.exc import IntegrityError

from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.im_intake.models import IntakeSlot
from app.modules.im_intake.templates import HARD_SLOT_KEYS
from app.modules.im_intake.promote import promote_to_resume
from app.modules.resume.models import Resume


def _make_complete_candidate(db, *, user_id=1, boss_id="b_promote",
                             name="候选", pdf_path="data/x.pdf"):
    c = IntakeCandidate(
        user_id=user_id, boss_id=boss_id, name=name,
        pdf_path=pdf_path, intake_status="complete",
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    for k in HARD_SLOT_KEYS:
        db.add(IntakeSlot(
            candidate_id=c.id, slot_key=k, slot_category="hard",
            value="filled", ask_count=1,
        ))
    db.commit()
    return c


class TestOneToOneInvariant:
    def test_promote_sets_intake_candidate_id_reverse_key(self, db_session):
        """阶段 C: promote 时 Resume.intake_candidate_id 反向回指 candidate.id"""
        c = _make_complete_candidate(db_session, boss_id="b_rev")
        r = promote_to_resume(db_session, c, user_id=1)
        db_session.commit()
        assert r.intake_candidate_id == c.id

    def test_two_candidates_cannot_promote_to_same_resume(self, db_session):
        """阶段 C: 两个 candidate 指同一 promoted_resume_id → DB 拒绝"""
        c1 = _make_complete_candidate(db_session, boss_id="b1")
        c2 = _make_complete_candidate(db_session, boss_id="b2")
        r = promote_to_resume(db_session, c1, user_id=1)
        db_session.commit()
        c2.promoted_resume_id = r.id
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_resume_intake_candidate_id_unique(self, db_session):
        """阶段 C: 两个 Resume 反向指同一 candidate → DB 拒绝"""
        c = _make_complete_candidate(db_session, boss_id="b_dup")
        r1 = promote_to_resume(db_session, c, user_id=1)
        db_session.commit()
        r2 = Resume(
            user_id=1, name="另一份", boss_id="b_other",
            intake_candidate_id=c.id,
        )
        db_session.add(r2)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_bidirectional_query(self, db_session):
        """阶段 C: candidate ↔ resume 双向都能 O(1) 查"""
        c = _make_complete_candidate(db_session, boss_id="b_bi")
        r = promote_to_resume(db_session, c, user_id=1)
        db_session.commit()
        # candidate → resume
        assert c.promoted_resume_id == r.id
        # resume → candidate
        assert r.intake_candidate_id == c.id

    def test_idempotent_promote_keeps_invariant(self, db_session):
        """重复 promote 同一 candidate 不破坏 1:1 关系"""
        c = _make_complete_candidate(db_session, boss_id="b_idem")
        r1 = promote_to_resume(db_session, c, user_id=1)
        db_session.commit()
        r2 = promote_to_resume(db_session, c, user_id=1)
        db_session.commit()
        assert r1.id == r2.id
        assert r2.intake_candidate_id == c.id
