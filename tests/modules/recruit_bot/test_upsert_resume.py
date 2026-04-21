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
