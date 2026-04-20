"""POST /api/screening/jobs/parse-jd — JD 字段解析端点."""
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from app.main import app

# mock LLM 返回的 JSON（parse_jd_fields 用）
_MOCK_PARSED = """{
  "title": "Python 后端工程师",
  "department": "研发部",
  "education_min": "本科",
  "work_years_min": 3,
  "work_years_max": 7,
  "salary_min": 20000,
  "salary_max": 40000,
  "required_skills": "Python,FastAPI,PostgreSQL",
  "soft_requirements": "有良好沟通能力，有大厂经历优先"
}"""


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("AGENTICHR_TEST_BYPASS_AUTH", "1")
    return TestClient(app)


def test_parse_jd_success(client):
    mock_llm = AsyncMock()
    mock_llm.complete = AsyncMock(return_value=_MOCK_PARSED)
    with patch("app.modules.screening.router.get_llm_provider", return_value=mock_llm):
        r = client.post("/api/screening/jobs/parse-jd", json={"jd_text": "招聘 Python 后端..."})
    assert r.status_code == 200
    data = r.json()
    assert data["title"] == "Python 后端工程师"
    assert data["education_min"] == "本科"
    assert data["work_years_min"] == 3
    assert data["required_skills"] == "Python,FastAPI,PostgreSQL"


def test_parse_jd_empty_text(client):
    r = client.post("/api/screening/jobs/parse-jd", json={"jd_text": "   "})
    assert r.status_code == 422


def test_parse_jd_llm_failure_fallback(client):
    """LLM 挂了时返回只有 jd_text 的 fallback（不报 500）."""
    mock_llm = AsyncMock()
    mock_llm.complete = AsyncMock(side_effect=Exception("timeout"))
    with patch("app.modules.screening.router.get_llm_provider", return_value=mock_llm):
        r = client.post("/api/screening/jobs/parse-jd", json={"jd_text": "招聘 Python 后端..."})
    assert r.status_code == 200
    data = r.json()
    assert data["title"] == ""   # fallback: 空字段
    assert data["jd_text"] == "招聘 Python 后端..."
