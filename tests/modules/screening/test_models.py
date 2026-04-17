"""岗位数据模型测试"""
from app.modules.screening.models import Job


def test_create_job(db_session):
    job = Job(
        title="Python后端开发",
        department="技术部",
        education_min="本科",
        work_years_min=3,
        work_years_max=10,
        salary_min=15000,
        salary_max=30000,
        required_skills="Python,FastAPI",
        soft_requirements="有大厂经历优先",
        greeting_templates="您好，请发送一份简历过来|你好，方便发一下简历吗",
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    assert job.id is not None
    assert job.title == "Python后端开发"
    assert job.is_active is True


def test_job_default_values(db_session):
    job = Job(title="测试岗位")
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    assert job.work_years_min == 0
    assert job.work_years_max == 99
    assert job.is_active is True
