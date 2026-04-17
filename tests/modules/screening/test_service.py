"""岗位管理与硬性条件筛选测试"""
from app.modules.screening.service import ScreeningService
from app.modules.screening.schemas import JobCreate, JobUpdate
from app.modules.resume.service import ResumeService
from app.modules.resume.schemas import ResumeCreate


def _create_test_resumes(db_session):
    rs = ResumeService(db_session)
    rs.create(ResumeCreate(
        name="候选人A", phone="13165338580", education="硕士",
        work_years=5, expected_salary_min=20000, expected_salary_max=30000,
        skills="Python,FastAPI,Docker", source="boss_zhipin",
    ))
    rs.create(ResumeCreate(
        name="候选人B", phone="13165338581", education="大专",
        work_years=1, expected_salary_min=8000, expected_salary_max=12000,
        skills="Python", source="boss_zhipin",
    ))
    rs.create(ResumeCreate(
        name="候选人C", phone="13165338582", education="本科",
        work_years=3, expected_salary_min=15000, expected_salary_max=20000,
        skills="Java,Spring,MySQL", source="boss_zhipin",
    ))


def test_create_job(db_session):
    service = ScreeningService(db_session)
    job = service.create_job(JobCreate(
        title="Python开发", education_min="本科",
        work_years_min=2, required_skills="Python",
    ))
    assert job.id is not None
    assert job.title == "Python开发"


def test_list_jobs(db_session):
    service = ScreeningService(db_session)
    service.create_job(JobCreate(title="岗位1"))
    service.create_job(JobCreate(title="岗位2"))
    result = service.list_jobs()
    assert result["total"] == 2


def test_update_job(db_session):
    service = ScreeningService(db_session)
    job = service.create_job(JobCreate(title="旧标题"))
    updated = service.update_job(job.id, JobUpdate(title="新标题"))
    assert updated.title == "新标题"


def test_screen_by_education(db_session):
    _create_test_resumes(db_session)
    service = ScreeningService(db_session)
    job = service.create_job(JobCreate(title="测试岗", education_min="本科"))
    result = service.screen_resumes(job.id)
    assert result["passed"] == 2
    assert result["rejected"] == 1


def test_screen_by_work_years(db_session):
    _create_test_resumes(db_session)
    service = ScreeningService(db_session)
    job = service.create_job(JobCreate(title="测试岗", work_years_min=3))
    result = service.screen_resumes(job.id)
    assert result["passed"] == 2
    assert result["rejected"] == 1


def test_screen_by_skills(db_session):
    _create_test_resumes(db_session)
    service = ScreeningService(db_session)
    job = service.create_job(JobCreate(title="测试岗", required_skills="Python"))
    result = service.screen_resumes(job.id)
    assert result["passed"] == 2
    assert result["rejected"] == 1


def test_screen_combined(db_session):
    _create_test_resumes(db_session)
    service = ScreeningService(db_session)
    job = service.create_job(JobCreate(
        title="测试岗", education_min="本科",
        work_years_min=3, required_skills="Python",
    ))
    result = service.screen_resumes(job.id)
    assert result["passed"] == 1
