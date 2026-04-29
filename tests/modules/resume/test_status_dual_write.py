"""spec 0429 阶段 A — IntakeCandidate.status / reject_reason 双写一致性

加列 + 渲染层去反查后，写 candidate.status 必须同步到 promoted Resume.status，
反之亦然（向后兼容旧路径）。
"""
import pytest

from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.im_intake.models import IntakeSlot
from app.modules.im_intake.templates import HARD_SLOT_KEYS
from app.modules.im_intake.promote import promote_to_resume
from app.modules.resume.models import Resume


def _seed(db, *, user_id=1, boss_id="b_status"):
    c = IntakeCandidate(
        user_id=user_id, boss_id=boss_id, name="N",
        pdf_path="data/x.pdf", intake_status="complete",
    )
    db.add(c); db.commit(); db.refresh(c)
    for k in HARD_SLOT_KEYS:
        db.add(IntakeSlot(
            candidate_id=c.id, slot_key=k, slot_category="hard",
            value="x", ask_count=1,
        ))
    db.commit()
    return c


class TestStatusColumnExists:
    def test_intake_candidate_has_status_column(self, db_session):
        """阶段 A migration 0022: IntakeCandidate.status 列存在"""
        c = _seed(db_session, boss_id="b_col")
        assert hasattr(c, "status")
        assert c.status in ("pending", "passed", "rejected")

    def test_intake_candidate_has_reject_reason_column(self, db_session):
        c = _seed(db_session, boss_id="b_rj_col")
        assert hasattr(c, "reject_reason")
        assert isinstance(c.reject_reason, str)


class TestStatusBackfill:
    def test_default_status_pending_for_collecting(self, db_session):
        c = IntakeCandidate(
            user_id=1, boss_id="b_pending", name="N",
            intake_status="collecting",
        )
        db_session.add(c); db_session.commit(); db_session.refresh(c)
        assert c.status == "pending"

    def test_promote_sets_status_passed(self, db_session):
        """promote 时 candidate.status 同步为 passed"""
        c = _seed(db_session, boss_id="b_pass")
        promote_to_resume(db_session, c, user_id=1)
        db_session.commit()
        db_session.refresh(c)
        assert c.status == "passed"


class TestDualWrite:
    def test_writing_candidate_status_propagates_to_resume(self, db_session, client):
        """通过 PATCH /api/resumes/{candidate.id} 改 status → promoted Resume.status 同步"""
        c = _seed(db_session, boss_id="b_dw1")
        promote_to_resume(db_session, c, user_id=1)
        db_session.commit()
        rid = c.promoted_resume_id
        resp = client.patch(f"/api/resumes/{c.id}",
                            json={"status": "rejected", "reject_reason": "学历不符"})
        assert resp.status_code == 200, resp.text
        db_session.expire_all()
        cand = db_session.query(IntakeCandidate).get(c.id)
        r = db_session.query(Resume).get(rid)
        assert cand.status == "rejected"
        assert cand.reject_reason == "学历不符"
        assert r.status == "rejected"
        assert r.reject_reason == "学历不符"


class TestRenderNoCrossTable:
    def test_resume_library_renders_status_from_candidate_only(self, db_session, client):
        """简历库 list 从 candidate.status 渲染，不再触发 Resume 反查"""
        c = _seed(db_session, boss_id="b_render")
        # 不 promote，只在 candidate 上设 status
        c.status = "passed"
        db_session.commit()
        resp = client.get("/api/resumes/")
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert any(i["id"] == c.id and i["status"] == "passed" for i in items)
