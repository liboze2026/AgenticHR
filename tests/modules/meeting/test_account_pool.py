"""腾讯会议账号池调度逻辑测试"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.config import settings
from app.modules.meeting.account_pool import configured_accounts, pick_available_account
from app.modules.resume.models import Resume
from app.modules.scheduling.models import Interview, Interviewer


def _make_setup(db):
    interviewer = Interviewer(name="面试官A")
    db.add(interviewer)
    resume = Resume(name="候选人A", phone="13000000001")
    db.add(resume)
    db.commit()
    return interviewer, resume


def _make_interview(db, resume, interviewer, start, end, meeting_link="", meeting_account="", status="scheduled"):
    iv = Interview(
        resume_id=resume.id,
        interviewer_id=interviewer.id,
        start_time=start,
        end_time=end,
        meeting_link=meeting_link,
        meeting_account=meeting_account,
        status=status,
    )
    db.add(iv)
    db.commit()
    return iv


def test_configured_accounts_parses_comma_list(monkeypatch):
    monkeypatch.setattr(settings, "tencent_meeting_accounts", "zhang, li ,wang")
    assert configured_accounts() == ["zhang", "li", "wang"]


def test_configured_accounts_empty():
    # 注意：默认值是 'default' 不是空，这里只验证 parse
    assert configured_accounts() != []


def test_pick_single_account_no_conflict(db_session, monkeypatch):
    monkeypatch.setattr(settings, "tencent_meeting_accounts", "a1")
    start = datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc)
    end = start + timedelta(hours=1)
    assert pick_available_account(db_session, start, end) == "a1"


def test_pick_picks_first_free_account(db_session, monkeypatch):
    monkeypatch.setattr(settings, "tencent_meeting_accounts", "a1,a2,a3")
    interviewer, resume = _make_setup(db_session)
    start = datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc)
    end = start + timedelta(hours=1)
    # a1 已在该时段占用
    _make_interview(db_session, resume, interviewer, start, end,
                    meeting_link="https://x", meeting_account="a1")
    # 应该挑下一个
    assert pick_available_account(db_session, start, end) == "a2"


def test_pick_all_busy_raises_409(db_session, monkeypatch):
    monkeypatch.setattr(settings, "tencent_meeting_accounts", "a1,a2")
    interviewer, resume = _make_setup(db_session)
    start = datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc)
    end = start + timedelta(hours=1)
    _make_interview(db_session, resume, interviewer, start, end,
                    meeting_link="https://x", meeting_account="a1")
    _make_interview(db_session, resume, interviewer, start, end,
                    meeting_link="https://y", meeting_account="a2")
    with pytest.raises(HTTPException) as exc:
        pick_available_account(db_session, start, end)
    assert exc.value.status_code == 409


def test_pick_ignores_cancelled(db_session, monkeypatch):
    monkeypatch.setattr(settings, "tencent_meeting_accounts", "a1,a2")
    interviewer, resume = _make_setup(db_session)
    start = datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc)
    end = start + timedelta(hours=1)
    # a1 占用但已取消 → 应该被忽略
    _make_interview(db_session, resume, interviewer, start, end,
                    meeting_link="https://x", meeting_account="a1", status="cancelled")
    assert pick_available_account(db_session, start, end) == "a1"


def test_pick_ignores_empty_meeting_link(db_session, monkeypatch):
    monkeypatch.setattr(settings, "tencent_meeting_accounts", "a1")
    interviewer, resume = _make_setup(db_session)
    start = datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc)
    end = start + timedelta(hours=1)
    # 面试存在但还没创建会议 → 不应该占用账号
    _make_interview(db_session, resume, interviewer, start, end,
                    meeting_link="", meeting_account="")
    assert pick_available_account(db_session, start, end) == "a1"


def test_pick_no_overlap_different_time(db_session, monkeypatch):
    monkeypatch.setattr(settings, "tencent_meeting_accounts", "a1")
    interviewer, resume = _make_setup(db_session)
    # 10:00-11:00 有 a1 占用
    _make_interview(db_session, resume, interviewer,
                    datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc),
                    datetime(2026, 5, 1, 11, 0, tzinfo=timezone.utc),
                    meeting_link="https://x", meeting_account="a1")
    # 11:00-12:00 查询：与上面紧邻不重叠
    assert pick_available_account(
        db_session,
        datetime(2026, 5, 1, 11, 0, tzinfo=timezone.utc),
        datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc),
    ) == "a1"


def test_pick_partial_overlap_counts_as_busy(db_session, monkeypatch):
    monkeypatch.setattr(settings, "tencent_meeting_accounts", "a1,a2")
    interviewer, resume = _make_setup(db_session)
    # 10:00-11:00 有 a1 占用
    _make_interview(db_session, resume, interviewer,
                    datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc),
                    datetime(2026, 5, 1, 11, 0, tzinfo=timezone.utc),
                    meeting_link="https://x", meeting_account="a1")
    # 10:30-11:30 查询：与上面半重叠 → a1 不可用，挑 a2
    result = pick_available_account(
        db_session,
        datetime(2026, 5, 1, 10, 30, tzinfo=timezone.utc),
        datetime(2026, 5, 1, 11, 30, tzinfo=timezone.utc),
    )
    assert result == "a2"


def test_pick_excludes_self(db_session, monkeypatch):
    """重建会议场景：当前 interview 自己的时段不应该把自己算成冲突。"""
    monkeypatch.setattr(settings, "tencent_meeting_accounts", "a1")
    interviewer, resume = _make_setup(db_session)
    start = datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc)
    end = start + timedelta(hours=1)
    iv = _make_interview(db_session, resume, interviewer, start, end,
                         meeting_link="https://old", meeting_account="a1")
    # 排除自己后 a1 应该可用
    assert pick_available_account(db_session, start, end, exclude_interview_id=iv.id) == "a1"
