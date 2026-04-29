"""回归测试 — 删除路径的级联清理.

现 bug：DELETE /api/resumes/{id} 在该 Resume 被 Interview FK 引用时挂 500
(IntegrityError: FOREIGN KEY constraint failed)。
clear-all 已经做了清理但单条 delete 没有。这组测试覆盖三条路径：

1. 通过 candidate.id 删（带 promoted Resume 且有 Interview/NotificationLog）
2. 通过 legacy Resume.id 删（无 candidate 反向链，但有 Interview）
3. 删 Interview 本身要清 NotificationLog 软引用孤儿
"""
from datetime import datetime, timedelta, timezone

from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.im_intake.models import IntakeSlot
from app.modules.im_intake.templates import HARD_SLOT_KEYS
from app.modules.resume.models import Resume
from app.modules.scheduling.models import Interview, Interviewer
from app.modules.notification.models import NotificationLog


def _seed_resume(session, *, user_id=1, name="测试简历", boss_id="b_x"):
    r = Resume(
        user_id=user_id, name=name, boss_id=boss_id,
        phone="13800000099", email="t@x.com",
        skills="Python", education="本科",
        bachelor_school="清华大学",
        work_years=3, seniority="中级",
        ai_parsed="yes", source="boss_zhipin",
        pdf_path="data/x.pdf", status="passed",
    )
    session.add(r)
    session.commit()
    session.refresh(r)
    return r


def _seed_candidate_with_resume(session, *, user_id=1, boss_id="b_e2e",
                                name="测试候选"):
    r = _seed_resume(session, user_id=user_id, name=name, boss_id=boss_id)
    c = IntakeCandidate(
        user_id=user_id, boss_id=boss_id, name=name,
        phone="13800000099", email="t@x.com",
        pdf_path="data/x.pdf", intake_status="complete",
        skills="Python", education="本科",
        bachelor_school="清华大学", school_tier="985",
        work_years=3, seniority="中级",
        promoted_resume_id=r.id,
    )
    session.add(c)
    session.commit()
    session.refresh(c)
    for k in HARD_SLOT_KEYS:
        session.add(IntakeSlot(
            candidate_id=c.id, slot_key=k, slot_category="hard",
            value="filled", ask_count=1,
        ))
    session.commit()
    return c, r


def _seed_interview_with_log(session, resume_id: int, user_id=1):
    """加一个 interviewer + interview + 两条 NotificationLog."""
    iv_er = Interviewer(name="面试官A", user_id=user_id)
    session.add(iv_er)
    session.commit()
    session.refresh(iv_er)

    now = datetime.now(timezone.utc)
    iv = Interview(
        user_id=user_id, resume_id=resume_id, interviewer_id=iv_er.id,
        start_time=now + timedelta(days=1),
        end_time=now + timedelta(days=1, hours=1),
        status="scheduled",
    )
    session.add(iv)
    session.commit()
    session.refresh(iv)

    log1 = NotificationLog(
        interview_id=iv.id, user_id=user_id,
        recipient_type="candidate", recipient_name="候选人",
        channel="email", recipient_address="t@x.com",
        subject="面试邀请", content="...",
        status="sent",
    )
    log2 = NotificationLog(
        interview_id=iv.id, user_id=user_id,
        recipient_type="interviewer", recipient_name="面试官A",
        channel="feishu", recipient_address="open_id_xxx",
        subject="面试通知", content="...",
        status="sent",
    )
    session.add_all([log1, log2])
    session.commit()
    return iv, [log1.id, log2.id]


# ── 1. candidate.id 入口（IntakeCandidate ⇄ Resume 1:1） ──────────────


def test_delete_resume_via_candidate_id_with_interview_cascades(client, db_session):
    c, r = _seed_candidate_with_resume(db_session, boss_id="b_cand_iv")
    iv, log_ids = _seed_interview_with_log(db_session, r.id)
    cid, rid, iv_id = c.id, r.id, iv.id

    resp = client.delete(f"/api/resumes/{cid}")
    assert resp.status_code == 204, resp.text

    db_session.expire_all()
    assert db_session.query(IntakeCandidate).get(cid) is None
    assert db_session.query(Resume).get(rid) is None
    assert db_session.query(Interview).get(iv_id) is None
    assert db_session.query(NotificationLog).filter(
        NotificationLog.id.in_(log_ids)
    ).count() == 0


# ── 2. legacy Resume.id 入口（无 candidate） ──────────────────────────


def test_delete_resume_via_legacy_id_with_interview_cascades(client, db_session):
    r = _seed_resume(db_session, name="legacy", boss_id="b_legacy")
    iv, log_ids = _seed_interview_with_log(db_session, r.id)
    rid, iv_id = r.id, iv.id

    resp = client.delete(f"/api/resumes/{rid}")
    assert resp.status_code == 204, resp.text

    db_session.expire_all()
    assert db_session.query(Resume).get(rid) is None
    assert db_session.query(Interview).get(iv_id) is None
    assert db_session.query(NotificationLog).filter(
        NotificationLog.id.in_(log_ids)
    ).count() == 0


# ── 3. Interview 自身删除清 NotificationLog ──────────────────────────


def test_delete_interview_clears_notification_logs(client, db_session):
    r = _seed_resume(db_session, name="iv_only", boss_id="b_iv_only")
    iv, log_ids = _seed_interview_with_log(db_session, r.id)
    rid, iv_id = r.id, iv.id

    resp = client.delete(f"/api/scheduling/interviews/{iv_id}")
    assert resp.status_code == 204, resp.text

    db_session.expire_all()
    assert db_session.query(Interview).get(iv_id) is None
    assert db_session.query(NotificationLog).filter(
        NotificationLog.id.in_(log_ids)
    ).count() == 0
    # Resume 不应被删
    assert db_session.query(Resume).get(rid) is not None


# ── 4. clear_all_resumes 也应清 Interview / NotificationLog ──────────


def test_clear_all_resumes_clears_interviews_and_logs(client, db_session):
    c1, r1 = _seed_candidate_with_resume(db_session, boss_id="b_clr1", name="清1")
    iv, log_ids = _seed_interview_with_log(db_session, r1.id)
    r1_id, iv_id = r1.id, iv.id

    resp = client.delete("/api/resumes/clear-all")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["deleted_resumes"] >= 1
    assert body["deleted_interviews"] >= 1
    assert body["deleted_notifications"] >= 2

    db_session.expire_all()
    assert db_session.query(Resume).get(r1_id) is None
    assert db_session.query(Interview).get(iv_id) is None
    assert db_session.query(NotificationLog).filter(
        NotificationLog.id.in_(log_ids)
    ).count() == 0


# ── 5. clear_all_interviews 清 NotificationLog ──────────────────────


# ── 6. delete_interviewer 级联清 cancelled Interview / Availability ──


def test_delete_interviewer_cascades_cancelled_interviews(client, db_session):
    """有 cancelled Interview + Availability 时仍可删 interviewer."""
    from app.modules.scheduling.models import InterviewerAvailability

    r = _seed_resume(db_session, name="iv_owner", boss_id="b_iv_o")
    iv_er = Interviewer(name="某面试官", user_id=1)
    db_session.add(iv_er)
    db_session.commit()
    db_session.refresh(iv_er)
    iv_er_id = iv_er.id

    now = datetime.now(timezone.utc)
    cancelled_iv = Interview(
        user_id=1, resume_id=r.id, interviewer_id=iv_er.id,
        start_time=now + timedelta(days=1),
        end_time=now + timedelta(days=1, hours=1),
        status="cancelled",
    )
    avail = InterviewerAvailability(
        interviewer_id=iv_er.id,
        start_time=now, end_time=now + timedelta(hours=1),
    )
    db_session.add_all([cancelled_iv, avail])
    db_session.commit()
    cancelled_iv_id = cancelled_iv.id
    log = NotificationLog(
        interview_id=cancelled_iv_id, user_id=1,
        recipient_type="candidate", recipient_name="候选人",
        channel="email", recipient_address="t@x.com",
        subject="x", content="x", status="sent",
    )
    db_session.add(log)
    db_session.commit()
    log_id = log.id

    resp = client.delete(f"/api/scheduling/interviewers/{iv_er_id}")
    assert resp.status_code == 204, resp.text

    db_session.expire_all()
    assert db_session.query(Interviewer).get(iv_er_id) is None
    assert db_session.query(Interview).get(cancelled_iv_id) is None
    assert db_session.query(NotificationLog).get(log_id) is None
    assert db_session.query(InterviewerAvailability).filter_by(
        interviewer_id=iv_er_id
    ).count() == 0


# ── 7. delete_job 级联清 cancelled Interview ─────────────────────────


def test_delete_job_cascades_cancelled_interviews(client, db_session):
    from app.modules.screening.models import Job

    job = Job(user_id=1, title="测试岗", department="dept", jd_text="JD")
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    job_id = job.id

    r = _seed_resume(db_session, name="job_r", boss_id="b_job_r")
    iv_er = Interviewer(name="官", user_id=1)
    db_session.add(iv_er)
    db_session.commit()
    db_session.refresh(iv_er)

    now = datetime.now(timezone.utc)
    cancelled_iv = Interview(
        user_id=1, resume_id=r.id, interviewer_id=iv_er.id, job_id=job_id,
        start_time=now + timedelta(days=1),
        end_time=now + timedelta(days=1, hours=1),
        status="cancelled",
    )
    db_session.add(cancelled_iv)
    db_session.commit()
    cancelled_iv_id = cancelled_iv.id

    resp = client.delete(f"/api/screening/jobs/{job_id}")
    assert resp.status_code == 204, resp.text

    db_session.expire_all()
    assert db_session.query(Job).get(job_id) is None
    assert db_session.query(Interview).get(cancelled_iv_id) is None


def test_clear_all_interviews_clears_notification_logs(client, db_session):
    r = _seed_resume(db_session, name="clr_iv", boss_id="b_clr_iv")
    iv, log_ids = _seed_interview_with_log(db_session, r.id)
    iv_id = iv.id
    _ = r.id  # touch in case of refresh later

    resp = client.delete("/api/scheduling/interviews/clear-all")
    assert resp.status_code == 200, resp.text

    db_session.expire_all()
    assert db_session.query(Interview).get(iv_id) is None
    assert db_session.query(NotificationLog).filter(
        NotificationLog.id.in_(log_ids)
    ).count() == 0
