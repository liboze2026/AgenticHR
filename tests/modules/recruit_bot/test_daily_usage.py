"""get_daily_usage — per-user 今日打招呼计数."""
import pytest
from datetime import datetime, timezone, timedelta


def _mk_user(db, user_id, daily_cap):
    from app.modules.auth.models import User
    u = User(id=user_id, username=f"u{user_id}", password_hash="x", daily_cap=daily_cap)
    db.add(u); db.commit()


def _mk_greeted(db, user_id, boss_id, greeted_at):
    from app.modules.resume.models import Resume
    db.add(Resume(
        user_id=user_id, name=f"n{boss_id}", boss_id=boss_id,
        source="boss_zhipin", greet_status="greeted",
        greeted_at=greeted_at,
    ))
    db.commit()


def test_daily_usage_zero_initially(db):
    from app.modules.recruit_bot.service import get_daily_usage
    _mk_user(db, 1, daily_cap=100)
    u = get_daily_usage(db, user_id=1)
    assert u.used == 0
    assert u.cap == 100
    assert u.remaining == 100


def test_daily_usage_counts_today_only(db):
    from app.modules.recruit_bot.service import get_daily_usage
    _mk_user(db, 1, daily_cap=100)
    now = datetime.now(timezone.utc)
    _mk_greeted(db, 1, "today_1", now)
    _mk_greeted(db, 1, "today_2", now)
    _mk_greeted(db, 1, "yesterday", now - timedelta(days=1, hours=1))
    u = get_daily_usage(db, user_id=1)
    assert u.used == 2
    assert u.remaining == 98


def test_daily_usage_per_user_isolated(db):
    from app.modules.recruit_bot.service import get_daily_usage
    _mk_user(db, 1, daily_cap=100)
    _mk_user(db, 2, daily_cap=50)
    now = datetime.now(timezone.utc)
    _mk_greeted(db, 1, "u1_x", now)
    _mk_greeted(db, 2, "u2_x", now)
    _mk_greeted(db, 2, "u2_y", now)
    ua = get_daily_usage(db, user_id=1)
    ub = get_daily_usage(db, user_id=2)
    assert ua.used == 1
    assert ub.used == 2
    assert ub.cap == 50


def test_daily_usage_ignores_non_greeted(db):
    from app.modules.recruit_bot.service import get_daily_usage
    from app.modules.resume.models import Resume
    _mk_user(db, 1, daily_cap=100)
    now = datetime.now(timezone.utc)
    db.add_all([
        Resume(user_id=1, name="a", boss_id="a", source="boss_zhipin",
               greet_status="pending_greet", greeted_at=now),
        Resume(user_id=1, name="b", boss_id="b", source="boss_zhipin",
               greet_status="failed", greeted_at=now),
    ])
    db.commit()
    u = get_daily_usage(db, user_id=1)
    assert u.used == 0
