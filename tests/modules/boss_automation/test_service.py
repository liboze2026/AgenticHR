"""Boss 自动化服务测试

使用 MockBossAdapter 进行内存测试，不依赖浏览器。
"""
import pytest
import asyncio

from app.adapters.boss.base import BossAdapter, BossCandidate, BossMessage
from app.modules.boss_automation.service import (
    BossAutomationService,
    JOB_GREETING_TEMPLATES,
    DEFAULT_GREETING,
)


class MockBossAdapter(BossAdapter):
    """内存实现的 Boss 适配器，用于测试"""

    def __init__(self):
        self._candidates: list[BossCandidate] = []
        self._sent_messages: list[tuple[str, str]] = []
        self._chat_messages: dict[str, list[BossMessage]] = {}
        self._available = True
        self._operations_today = 0

    def add_candidate(self, candidate: BossCandidate):
        self._candidates.append(candidate)

    def add_chat_message(self, boss_id: str, message: BossMessage):
        if boss_id not in self._chat_messages:
            self._chat_messages[boss_id] = []
        self._chat_messages[boss_id].append(message)

    async def get_new_greetings(self) -> list[BossCandidate]:
        return list(self._candidates)

    async def send_greeting_reply(self, boss_id: str, message: str) -> bool:
        self._sent_messages.append((boss_id, message))
        self._operations_today += 1
        return True

    async def get_candidate_info(self, boss_id: str) -> BossCandidate | None:
        for c in self._candidates:
            if c.boss_id == boss_id:
                return c
        return None

    async def get_chat_messages(self, boss_id: str) -> list[BossMessage]:
        return self._chat_messages.get(boss_id, [])

    async def download_pdf(self, pdf_url: str, save_path: str) -> bool:
        return True

    async def is_available(self) -> bool:
        return self._available

    async def list_chat_index(self) -> list[BossCandidate]:
        return list(self._candidates)

    async def send_message(self, boss_id: str, text: str) -> bool:
        self._sent_messages.append((boss_id, text))
        self._operations_today += 1
        return True

    async def click_request_resume(self, boss_id: str) -> bool:
        self._operations_today += 1
        return True

    async def list_received_resumes(self) -> list[tuple[str, str]]:
        return []


@pytest.fixture
def mock_adapter():
    adapter = MockBossAdapter()
    adapter.add_candidate(BossCandidate(name="张三", boss_id="u001"))
    adapter.add_candidate(BossCandidate(name="李四", boss_id="u002"))
    return adapter


@pytest.fixture
def service(db_session, mock_adapter):
    return BossAutomationService(db=db_session, adapter=mock_adapter)


def test_auto_greet(service, mock_adapter):
    """验证自动打招呼功能"""
    result = asyncio.get_event_loop().run_until_complete(
        service.auto_greet(max_count=5)
    )
    assert result.total_found == 2
    assert result.greeted_count == 2
    assert len(result.candidates) == 2
    assert len(mock_adapter._sent_messages) == 2
    # 使用默认招呼语
    assert mock_adapter._sent_messages[0][1] == DEFAULT_GREETING


def test_auto_greet_with_job_template(service, mock_adapter):
    """验证职位模板招呼功能"""
    JOB_GREETING_TEMPLATES["job123"] = ["你好，欢迎加入我们团队！"]
    try:
        result = asyncio.get_event_loop().run_until_complete(
            service.auto_greet(job_id="job123", max_count=5)
        )
        assert result.greeted_count == 2
        assert mock_adapter._sent_messages[0][1] == "你好，欢迎加入我们团队！"
    finally:
        JOB_GREETING_TEMPLATES.pop("job123", None)


def test_auto_greet_no_adapter(db_session):
    """无适配器时优雅处理"""
    service = BossAutomationService(db=db_session, adapter=None)
    result = asyncio.get_event_loop().run_until_complete(
        service.auto_greet(max_count=5)
    )
    assert result.greeted_count == 0
    assert "未配置" in result.message


def test_get_status(service):
    """测试状态获取"""
    result = asyncio.get_event_loop().run_until_complete(service.get_status())
    assert result.available is True
    assert result.adapter_type == "MockBossAdapter"
    assert result.max_operations_per_day > 0


def test_boss_status_api(client):
    """测试 Boss 状态 API 路由"""
    response = client.get("/api/boss/status")
    assert response.status_code == 200
    data = response.json()
    assert "available" in data
    assert data["available"] is False  # 默认无适配器
    assert "adapter_type" in data
