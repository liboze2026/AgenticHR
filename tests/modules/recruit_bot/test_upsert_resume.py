"""upsert_resume_by_boss_id — UNIQUE(user_id, boss_id) 幂等.

``db`` 及 ``_seed_m2_schema`` 来自 ``conftest.py``, T3/T4/T5 共用.
"""


def _mk_candidate(boss_id="xyz001", name="张三"):
    from app.modules.recruit_bot.schemas import ScrapedCandidate
    return ScrapedCandidate(
        name=name, boss_id=boss_id, age=28,
        education="本科", school="XX 大学", major="计算机",
        intended_job="后端", work_years=3,
        skill_tags=["Python", "Redis"],
        raw_text="full text",
    )


def test_upsert_creates_new_resume(db):
    from app.modules.recruit_bot.service import upsert_resume_by_boss_id
    r = upsert_resume_by_boss_id(db, user_id=1, candidate=_mk_candidate())
    assert r.id > 0
    assert r.name == "张三"
    assert r.boss_id == "xyz001"
    assert r.user_id == 1
    assert r.source == "boss_zhipin"
    assert r.skills == "Python,Redis"
    assert r.greet_status == "none"


def test_upsert_idempotent_same_boss_id(db):
    from app.modules.recruit_bot.service import upsert_resume_by_boss_id
    r1 = upsert_resume_by_boss_id(db, user_id=1, candidate=_mk_candidate())
    r2 = upsert_resume_by_boss_id(
        db, user_id=1, candidate=_mk_candidate(name="张三改名"),
    )
    assert r1.id == r2.id
    assert r2.name == "张三改名"  # 字段更新


def test_upsert_different_users_different_rows(db):
    from app.modules.recruit_bot.service import upsert_resume_by_boss_id
    r1 = upsert_resume_by_boss_id(db, user_id=1, candidate=_mk_candidate())
    r2 = upsert_resume_by_boss_id(db, user_id=2, candidate=_mk_candidate())
    assert r1.id != r2.id


def test_upsert_does_not_clobber_greet_status(db):
    """既有 greet_status='greeted' 的 resume 再 upsert 不把状态重置."""
    from app.modules.recruit_bot.service import upsert_resume_by_boss_id
    r1 = upsert_resume_by_boss_id(db, user_id=1, candidate=_mk_candidate())
    r1.greet_status = "greeted"
    db.commit()
    r2 = upsert_resume_by_boss_id(db, user_id=1, candidate=_mk_candidate(name="新名"))
    assert r2.greet_status == "greeted"  # 未被清


def test_upsert_skill_tags_csv_conversion(db):
    from app.modules.recruit_bot.service import upsert_resume_by_boss_id
    from app.modules.recruit_bot.schemas import ScrapedCandidate
    c = ScrapedCandidate(
        name="李四", boss_id="zzz",
        skill_tags=["Java", "Spring", "Redis"],
    )
    r = upsert_resume_by_boss_id(db, user_id=1, candidate=c)
    assert r.skills == "Java,Spring,Redis"


def test_upsert_raw_text_includes_all_fields(db):
    """raw_text 回填成调试用的 summary, 所有字段拼接."""
    from app.modules.recruit_bot.service import upsert_resume_by_boss_id
    c = _mk_candidate()
    r = upsert_resume_by_boss_id(db, user_id=1, candidate=c)
    assert "Python" in r.raw_text
    assert "张三" in r.raw_text or "后端" in r.raw_text


def test_upsert_catches_integrity_error_and_returns_existing(db, monkeypatch):
    """并发 race: 首轮 SELECT 漏看对手, INSERT 触发 UNIQUE → service 捕 IntegrityError,
    rollback, 重新 SELECT, 返回对手插入的获胜行. 该测试证明 try/except 分支有效."""
    from app.modules.recruit_bot import service as svc
    from app.modules.resume.models import Resume

    # 获胜行: 模拟另一并发 writer 已提交的插入
    winner = Resume(
        user_id=1, name="race_winner", boss_id="race_boss",
        source="boss_zhipin", greet_status="none",
    )
    db.add(winner)
    db.commit()
    winner_id = winner.id

    cand = _mk_candidate(boss_id="race_boss", name="race_loser")

    # 拦截首个针对 Resume 的 SELECT, 强制返回 None 以走 INSERT 分支.
    # 这模拟了 "两路并发 reader 都没看到对方" 的 race 窗口.
    real_query = db.query
    call_n = {"c": 0}

    def _query_patch(*args, **kwargs):
        q = real_query(*args, **kwargs)
        if (
            call_n["c"] == 0
            and args
            and getattr(args[0], "__name__", "") == "Resume"
        ):
            call_n["c"] += 1

            class _Fake:
                def filter(self, *a, **kw):
                    return self

                def first(self):
                    return None

            return _Fake()
        return q

    monkeypatch.setattr(db, "query", _query_patch)

    # SELECT 返 None → INSERT → UNIQUE 触发 IntegrityError →
    # rollback → 二次 SELECT 找到 winner → 返回 winner.
    r = svc.upsert_resume_by_boss_id(db, user_id=1, candidate=cand)
    assert r.id == winner_id
    assert r.name == "race_winner"  # 未被 loser 覆盖


def test_upsert_source_has_integrity_error_handler():
    """静态保证: upsert_resume_by_boss_id 函数源码含 IntegrityError + rollback.

    防止 refactor 意外把 race-catch 分支删掉 (或改成只有 try/except 外层).
    """
    import inspect
    from app.modules.recruit_bot.service import upsert_resume_by_boss_id

    src = inspect.getsource(upsert_resume_by_boss_id)
    assert "IntegrityError" in src, "upsert 必须 catch IntegrityError 以处理并发 race"
    assert "rollback" in src.lower(), "catch 分支必须 rollback"
