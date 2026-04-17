"""AI 评估 service 测试"""
import pytest
from app.modules.ai_evaluation.service import AIEvaluationService
from app.modules.resume.models import Resume
from app.modules.screening.models import Job


class MockAIProvider:
    async def evaluate_resume(self, resume_text, job_requirements):
        return {
            "score": 85,
            "strengths": ["技能匹配", "经验丰富"],
            "risks": ["薪资偏高"],
            "recommendation": "推荐",
            "summary": "综合素质不错",
        }

    def is_configured(self):
        return True


@pytest.fixture
def ai_service(db_session):
    return AIEvaluationService(db_session, ai_provider=MockAIProvider())


@pytest.fixture
def test_data(db_session):
    job = Job(title="Python开发", education_min="本科", required_skills="Python", soft_requirements="有大厂经历优先")
    db_session.add(job)
    resume = Resume(name="测试候选人", phone="13165338580", education="本科", work_years=3, skills="Python,Django", status="passed")
    db_session.add(resume)
    db_session.commit()
    db_session.refresh(job)
    db_session.refresh(resume)
    return {"job_id": job.id, "resume_id": resume.id}


@pytest.mark.asyncio
async def test_evaluate_single(ai_service, test_data):
    result = await ai_service.evaluate_single(test_data["resume_id"], test_data["job_id"])
    assert result["status"] == "success"
    assert result["score"] == 85
    assert result["recommendation"] == "推荐"
    assert len(result["strengths"]) > 0


@pytest.mark.asyncio
async def test_evaluate_single_resume_not_found(ai_service, test_data):
    result = await ai_service.evaluate_single(99999, test_data["job_id"])
    assert result["status"] == "failed"


@pytest.mark.asyncio
async def test_evaluate_batch(ai_service, test_data, db_session):
    r2 = Resume(name="候选人2", phone="13165338581", skills="Python", status="passed")
    db_session.add(r2)
    db_session.commit()

    result = await ai_service.evaluate_batch(test_data["job_id"])
    assert result["total"] == 2
    assert result["succeeded"] == 2
    assert result["results"][0]["score"] >= result["results"][1]["score"]
