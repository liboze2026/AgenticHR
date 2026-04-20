"""简历数据模型测试"""
from datetime import datetime
from app.modules.resume.models import Resume


def test_create_resume(db_session):
    resume = Resume(
        name="张三",
        phone="13800138000",
        email="zhangsan@example.com",
        education="本科",
        work_years=5,
        expected_salary_min=15000,
        expected_salary_max=25000,
        job_intention="Python开发工程师",
        skills="Python,FastAPI,SQLAlchemy",
        work_experience="某公司 高级开发工程师 3年",
        project_experience="电商平台后端开发",
        self_evaluation="热爱编程",
        source="boss_zhipin",
        raw_text="完整简历文本内容...",
        pdf_path="/data/resumes/zhangsan.pdf",
    )
    db_session.add(resume)
    db_session.commit()
    db_session.refresh(resume)

    assert resume.id is not None
    assert resume.name == "张三"
    assert resume.phone == "13800138000"
    assert resume.status == "passed"
    assert isinstance(resume.created_at, datetime)


def test_resume_duplicate_check(db_session):
    """同名同手机号视为重复"""
    resume1 = Resume(name="李四", phone="13900139000", source="boss_zhipin")
    db_session.add(resume1)
    db_session.commit()

    existing = (
        db_session.query(Resume)
        .filter(Resume.name == "李四", Resume.phone == "13900139000")
        .first()
    )
    assert existing is not None
    assert existing.id == resume1.id
