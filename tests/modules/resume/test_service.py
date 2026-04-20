"""简历业务逻辑测试"""
from app.modules.resume.service import ResumeService
from app.modules.resume.schemas import ResumeCreate, ResumeUpdate


def test_create_resume(db_session):
    service = ResumeService(db_session)
    data = ResumeCreate(
        name="王五",
        phone="13700137000",
        email="wangwu@example.com",
        education="硕士",
        work_years=3,
        source="boss_zhipin",
    )
    resume, is_new = service.create(data)
    assert is_new is True
    assert resume.id is not None
    assert resume.name == "王五"
    assert resume.status == "passed"


def test_create_duplicate_resume(db_session):
    service = ResumeService(db_session)
    data = ResumeCreate(name="赵六", phone="13600136000", source="boss_zhipin")
    service.create(data)
    duplicate, is_new = service.create(data)
    assert is_new is False
    assert duplicate is not None  # 返回已有记录而不是 None


def test_get_resume_by_id(db_session):
    service = ResumeService(db_session)
    data = ResumeCreate(name="钱七", phone="13500135000")
    created, _ = service.create(data)
    fetched = service.get_by_id(created.id)
    assert fetched is not None
    assert fetched.name == "钱七"


def test_list_resumes_with_pagination(db_session):
    service = ResumeService(db_session)
    for i in range(15):
        service.create(ResumeCreate(name=f"候选人{i}", phone=f"1380013{i:04d}"))

    result = service.list(page=1, page_size=10)
    assert result["total"] == 15
    assert len(result["items"]) == 10
    assert result["page"] == 1

    result2 = service.list(page=2, page_size=10)
    assert len(result2["items"]) == 5


def test_list_resumes_filter_by_status(db_session):
    service = ResumeService(db_session)
    r1, _ = service.create(ResumeCreate(name="甲", phone="13165338580"))
    # default status is now "passed"; reject 甲 so only 乙 passes the filter
    service.update(r1.id, ResumeUpdate(status="rejected"))
    service.create(ResumeCreate(name="乙", phone="13165338581"))

    result = service.list(status="passed")
    assert result["total"] == 1
    assert result["items"][0].name == "乙"


def test_update_resume_status(db_session):
    service = ResumeService(db_session)
    resume, _ = service.create(ResumeCreate(name="孙八", phone="13400134000"))
    updated = service.update(resume.id, ResumeUpdate(status="rejected", reject_reason="工作年限不足"))
    assert updated.status == "rejected"
    assert updated.reject_reason == "工作年限不足"


def test_search_resumes_by_keyword(db_session):
    service = ResumeService(db_session)
    service.create(ResumeCreate(name="张Java", phone="13165338583", skills="Java,Spring"))
    service.create(ResumeCreate(name="李Python", phone="13165338584", skills="Python,FastAPI"))

    result = service.list(keyword="Java")
    assert result["total"] == 1
    assert result["items"][0].name == "张Java"


def test_duplicate_updates_missing_info(db_session):
    """重复创建时应补充已有记录缺少的信息"""
    service = ResumeService(db_session)
    r1, _ = service.create(ResumeCreate(name="测试", phone="13900001111"))
    assert r1.email == ""

    r2, is_new = service.create(ResumeCreate(name="测试", phone="13900001111", email="test@test.com"))
    assert is_new is False
    assert r2.id == r1.id
    assert r2.email == "test@test.com"
