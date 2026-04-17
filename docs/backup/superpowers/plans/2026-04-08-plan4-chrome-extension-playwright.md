# Plan 4: Chrome 插件 + Playwright 适配器 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 实现 Chrome 插件和 Playwright 两种方式操作 Boss 直聘，完成自动打招呼、简历采集、PDF 下载，并包含反检测策略。

**Architecture:** Chrome 插件作为独立前端工程，通过 HTTP 与本地后端通信。Playwright 适配器在后端内运行，实现相同的 BossAdapter 接口。两者互为备份。

**Tech Stack:** Chrome Extension (Manifest V3, vanilla JS), Playwright (Python), FastAPI

---

### Task 1: Playwright Boss 直聘适配器

**Files:**
- Create: `app/adapters/boss/playwright_adapter.py`
- Create: `tests/adapters/__init__.py`
- Create: `tests/adapters/test_boss_playwright.py`

**playwright_adapter.py:**
```python
"""Playwright Boss 直聘自动化适配器

通过 Playwright 控制 Chrome 浏览器操作 Boss 直聘页面。
实现 BossAdapter 接口，与 Chrome 插件方案互为备选。
"""
import asyncio
import logging
import random
from pathlib import Path

from app.adapters.boss.base import BossAdapter, BossCandidate, BossMessage
from app.config import settings

logger = logging.getLogger(__name__)


class PlaywrightBossAdapter(BossAdapter):
    """Playwright 实现的 Boss 直聘适配器"""

    def __init__(self, user_data_dir: str = "./data/chrome_profile"):
        self.user_data_dir = user_data_dir
        self._browser = None
        self._context = None
        self._page = None

    async def _ensure_browser(self):
        """确保浏览器已启动，使用用户自己的 Chrome profile 保持登录态"""
        if self._page and not self._page.is_closed():
            return

        try:
            from playwright.async_api import async_playwright
            self._playwright = await async_playwright().start()
            self._context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=self.user_data_dir,
                headless=False,  # 有界面模式，让 HR 可以观察
                args=["--disable-blink-features=AutomationControlled"],
                viewport={"width": 1280, "height": 800},
            )
            self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
            # 移除 webdriver 标记
            await self._page.add_init_script("delete Object.getPrototypeOf(navigator).webdriver")
            logger.info("Playwright 浏览器已启动")
        except Exception as e:
            logger.error(f"启动浏览器失败: {e}")
            raise

    async def _random_delay(self):
        """随机延迟，模拟人工操作"""
        delay = random.uniform(settings.boss_delay_min, settings.boss_delay_max)
        await asyncio.sleep(delay)

    async def _human_like_click(self, selector: str):
        """模拟人类点击（先移动鼠标到元素，再点击）"""
        element = await self._page.wait_for_selector(selector, timeout=10000)
        if element:
            box = await element.bounding_box()
            if box:
                # 在元素范围内随机偏移点击
                x = box["x"] + random.uniform(box["width"] * 0.2, box["width"] * 0.8)
                y = box["y"] + random.uniform(box["height"] * 0.2, box["height"] * 0.8)
                await self._page.mouse.move(x, y, steps=random.randint(5, 15))
                await asyncio.sleep(random.uniform(0.1, 0.3))
                await self._page.mouse.click(x, y)

    async def is_available(self) -> bool:
        try:
            from playwright.async_api import async_playwright
            return True
        except ImportError:
            return False

    async def get_new_greetings(self) -> list[BossCandidate]:
        """获取新的打招呼消息列表"""
        await self._ensure_browser()
        candidates = []

        try:
            await self._page.goto("https://www.zhipin.com/web/boss/message", wait_until="networkidle")
            await self._random_delay()

            # 获取消息列表中的候选人
            items = await self._page.query_selector_all(".chat-item")
            for item in items:
                name_el = await item.query_selector(".name")
                name = await name_el.inner_text() if name_el else ""
                if name:
                    candidates.append(BossCandidate(name=name))

            logger.info(f"获取到 {len(candidates)} 个新消息")
        except Exception as e:
            logger.error(f"获取打招呼消息失败: {e}")

        return candidates

    async def send_greeting_reply(self, boss_id: str, message: str) -> bool:
        """回复候选人打招呼消息"""
        await self._ensure_browser()

        try:
            await self._random_delay()

            # 在聊天输入框中输入消息
            input_el = await self._page.wait_for_selector(".chat-input textarea, .chat-input [contenteditable]", timeout=5000)
            if input_el:
                await input_el.click()
                # 模拟逐字输入
                for char in message:
                    await input_el.type(char, delay=random.randint(50, 150))
                    if random.random() < 0.1:  # 10% 概率额外停顿
                        await asyncio.sleep(random.uniform(0.3, 0.8))

                await self._random_delay()

                # 点击发送按钮
                send_btn = await self._page.query_selector(".btn-send, [data-type='send']")
                if send_btn:
                    await send_btn.click()
                    logger.info(f"已回复候选人 {boss_id}")
                    return True

            return False
        except Exception as e:
            logger.error(f"回复消息失败: {e}")
            return False

    async def get_candidate_info(self, boss_id: str) -> BossCandidate | None:
        """获取候选人详细信息"""
        await self._ensure_browser()

        try:
            await self._random_delay()

            # 从当前聊天页面或候选人详情页提取信息
            name = ""
            name_el = await self._page.query_selector(".user-name, .name")
            if name_el:
                name = await name_el.inner_text()

            return BossCandidate(name=name, boss_id=boss_id) if name else None
        except Exception as e:
            logger.error(f"获取候选人信息失败: {e}")
            return None

    async def get_chat_messages(self, boss_id: str) -> list[BossMessage]:
        """获取与候选人的聊天记录"""
        await self._ensure_browser()
        messages = []

        try:
            msg_items = await self._page.query_selector_all(".chat-message, .msg-item")
            for item in msg_items:
                content_el = await item.query_selector(".msg-text, .text")
                content = await content_el.inner_text() if content_el else ""

                # 检查是否有 PDF 附件
                pdf_el = await item.query_selector("a[href*='.pdf'], .file-card")
                is_pdf = pdf_el is not None
                pdf_url = ""
                if pdf_el:
                    pdf_url = await pdf_el.get_attribute("href") or ""

                messages.append(BossMessage(
                    sender_id=boss_id,
                    sender_name="",
                    content=content,
                    is_pdf=is_pdf,
                    pdf_url=pdf_url,
                ))
        except Exception as e:
            logger.error(f"获取聊天记录失败: {e}")

        return messages

    async def download_pdf(self, pdf_url: str, save_path: str) -> bool:
        """下载候选人的 PDF 简历"""
        await self._ensure_browser()

        try:
            Path(save_path).parent.mkdir(parents=True, exist_ok=True)

            async with self._page.expect_download() as download_info:
                await self._page.goto(pdf_url)
            download = await download_info.value
            await download.save_as(save_path)
            logger.info(f"PDF 已下载: {save_path}")
            return True
        except Exception as e:
            logger.error(f"PDF 下载失败: {e}")
            return False

    async def close(self):
        """关闭浏览器"""
        if self._context:
            await self._context.close()
        if hasattr(self, '_playwright') and self._playwright:
            await self._playwright.stop()
        logger.info("Playwright 浏览器已关闭")
```

**test_boss_playwright.py:**
```python
"""Playwright Boss 适配器测试（不启动真实浏览器）"""
import pytest
from app.adapters.boss.playwright_adapter import PlaywrightBossAdapter
from app.adapters.boss.base import BossAdapter


def test_playwright_adapter_implements_interface():
    """确认 PlaywrightBossAdapter 实现了 BossAdapter 接口"""
    adapter = PlaywrightBossAdapter()
    assert isinstance(adapter, BossAdapter)


def test_playwright_adapter_has_required_methods():
    """确认所有必要方法存在"""
    adapter = PlaywrightBossAdapter()
    assert hasattr(adapter, "get_new_greetings")
    assert hasattr(adapter, "send_greeting_reply")
    assert hasattr(adapter, "get_candidate_info")
    assert hasattr(adapter, "get_chat_messages")
    assert hasattr(adapter, "download_pdf")
    assert hasattr(adapter, "is_available")
    assert hasattr(adapter, "close")


def test_playwright_adapter_default_config():
    adapter = PlaywrightBossAdapter()
    assert adapter.user_data_dir == "./data/chrome_profile"

    adapter2 = PlaywrightBossAdapter(user_data_dir="/custom/path")
    assert adapter2.user_data_dir == "/custom/path"
```

Commit: `git commit -m "feat: add Playwright Boss adapter with anti-detection and human-like behavior"`

---

### Task 2: Boss 直聘自动化控制 Service

**Files:**
- Create: `app/modules/boss_automation/__init__.py`
- Create: `app/modules/boss_automation/schemas.py`
- Create: `app/modules/boss_automation/service.py`
- Create: `app/modules/boss_automation/router.py`
- Create: `tests/modules/boss_automation/__init__.py`
- Create: `tests/modules/boss_automation/test_service.py`
- Create: `tests/modules/boss_automation/test_router.py`
- Modify: `app/main.py`

**schemas.py:**
```python
"""Boss 直聘自动化操作数据结构"""
from pydantic import BaseModel, Field


class AutoGreetRequest(BaseModel):
    """自动打招呼请求"""
    job_id: int | None = None
    message: str = ""  # 为空则从岗位话术模板随机选取
    max_count: int = Field(default=10, ge=1, le=50)


class AutoGreetResponse(BaseModel):
    total_found: int
    greeted: int
    skipped: int
    errors: int


class CollectResumesResponse(BaseModel):
    total_checked: int
    new_resumes: int
    duplicates: int
    errors: int


class BossStatusResponse(BaseModel):
    adapter_type: str
    is_available: bool
    operations_today: int
    max_operations_today: int
```

**service.py:**
```python
"""Boss 直聘自动化操作业务逻辑

协调 BossAdapter（插件或 Playwright）与简历模块，
实现自动打招呼、简历采集等流程。
"""
import logging
import random
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.config import settings
from app.adapters.boss.base import BossAdapter
from app.modules.resume.service import ResumeService
from app.modules.resume.schemas import ResumeCreate
from app.modules.screening.models import Job

logger = logging.getLogger(__name__)


class BossAutomationService:
    def __init__(self, db: Session, adapter: BossAdapter | None = None):
        self.db = db
        self.adapter = adapter
        self.resume_service = ResumeService(db)
        self._operations_today = 0

    def _get_greeting_message(self, job_id: int | None = None, custom_message: str = "") -> str:
        """获取打招呼话术"""
        if custom_message:
            return custom_message

        if job_id:
            job = self.db.query(Job).filter(Job.id == job_id).first()
            if job and job.greeting_templates:
                templates = [t.strip() for t in job.greeting_templates.split("|") if t.strip()]
                if templates:
                    return random.choice(templates)

        return "您好，感谢您的关注！方便发一份简历过来吗？"

    async def auto_greet(self, job_id: int | None = None, message: str = "", max_count: int = 10) -> dict:
        """自动回复打招呼消息"""
        if not self.adapter:
            return {"total_found": 0, "greeted": 0, "skipped": 0, "errors": 0}

        if not await self.adapter.is_available():
            logger.warning("Boss 适配器不可用")
            return {"total_found": 0, "greeted": 0, "skipped": 0, "errors": 0}

        candidates = await self.adapter.get_new_greetings()
        total = len(candidates)
        greeted = 0
        skipped = 0
        errors = 0

        for candidate in candidates[:max_count]:
            if self._operations_today >= settings.boss_max_operations_per_day:
                logger.warning("已达到每日操作上限")
                skipped += len(candidates[greeted + skipped + errors:])
                break

            try:
                greeting = self._get_greeting_message(job_id, message)
                success = await self.adapter.send_greeting_reply(candidate.boss_id, greeting)
                if success:
                    greeted += 1
                    self._operations_today += 1
                else:
                    errors += 1
            except Exception as e:
                logger.error(f"打招呼失败 [{candidate.name}]: {e}")
                errors += 1

        return {"total_found": total, "greeted": greeted, "skipped": skipped, "errors": errors}

    async def collect_resumes(self) -> dict:
        """采集候选人发来的简历"""
        if not self.adapter:
            return {"total_checked": 0, "new_resumes": 0, "duplicates": 0, "errors": 0}

        candidates = await self.adapter.get_new_greetings()
        new_resumes = 0
        duplicates = 0
        errors = 0

        for candidate in candidates:
            try:
                messages = await self.adapter.get_chat_messages(candidate.boss_id)
                for msg in messages:
                    if msg.is_pdf and msg.pdf_url:
                        # 下载 PDF
                        import time
                        save_path = f"{settings.resume_storage_path}/{int(time.time())}_{candidate.name}.pdf"
                        downloaded = await self.adapter.download_pdf(msg.pdf_url, save_path)
                        if downloaded:
                            result = self.resume_service.create(ResumeCreate(
                                name=candidate.name,
                                phone=candidate.phone,
                                email=candidate.email,
                                education=candidate.education,
                                source="boss_zhipin",
                                pdf_path=save_path,
                            ))
                            if result:
                                new_resumes += 1
                            else:
                                duplicates += 1
            except Exception as e:
                logger.error(f"采集简历失败 [{candidate.name}]: {e}")
                errors += 1

        return {"total_checked": len(candidates), "new_resumes": new_resumes, "duplicates": duplicates, "errors": errors}

    def get_status(self) -> dict:
        return {
            "adapter_type": settings.boss_adapter,
            "is_available": self.adapter is not None,
            "operations_today": self._operations_today,
            "max_operations_today": settings.boss_max_operations_per_day,
        }
```

**router.py:**
```python
"""Boss 直聘自动化操作 API 路由"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.boss_automation.service import BossAutomationService
from app.modules.boss_automation.schemas import (
    AutoGreetRequest, AutoGreetResponse,
    CollectResumesResponse, BossStatusResponse,
)

router = APIRouter()


def get_service(db: Session = Depends(get_db)) -> BossAutomationService:
    return BossAutomationService(db)  # adapter=None, 需要运行时注入


@router.post("/greet", response_model=AutoGreetResponse)
async def auto_greet(request: AutoGreetRequest, service: BossAutomationService = Depends(get_service)):
    return await service.auto_greet(request.job_id, request.message, request.max_count)


@router.post("/collect", response_model=CollectResumesResponse)
async def collect_resumes(service: BossAutomationService = Depends(get_service)):
    return await service.collect_resumes()


@router.get("/status", response_model=BossStatusResponse)
def boss_status(service: BossAutomationService = Depends(get_service)):
    return service.get_status()
```

**test_service.py:**
```python
"""Boss 自动化 service 测试"""
import pytest
from app.modules.boss_automation.service import BossAutomationService
from app.modules.screening.models import Job
from app.adapters.boss.base import BossAdapter, BossCandidate, BossMessage


class MockBossAdapter(BossAdapter):
    def __init__(self):
        self.greetings_sent = []

    async def get_new_greetings(self):
        return [
            BossCandidate(name="候选人A", boss_id="a1"),
            BossCandidate(name="候选人B", boss_id="b2"),
        ]

    async def send_greeting_reply(self, boss_id, message):
        self.greetings_sent.append({"boss_id": boss_id, "message": message})
        return True

    async def get_candidate_info(self, boss_id):
        return BossCandidate(name="测试", boss_id=boss_id)

    async def get_chat_messages(self, boss_id):
        return []

    async def download_pdf(self, pdf_url, save_path):
        return True

    async def is_available(self):
        return True


@pytest.mark.asyncio
async def test_auto_greet(db_session):
    adapter = MockBossAdapter()
    service = BossAutomationService(db_session, adapter=adapter)
    result = await service.auto_greet(max_count=5)
    assert result["total_found"] == 2
    assert result["greeted"] == 2
    assert len(adapter.greetings_sent) == 2


@pytest.mark.asyncio
async def test_auto_greet_with_job_template(db_session):
    job = Job(title="测试岗", greeting_templates="你好，请发简历|您好，方便发简历吗")
    db_session.add(job)
    db_session.commit()

    adapter = MockBossAdapter()
    service = BossAutomationService(db_session, adapter=adapter)
    result = await service.auto_greet(job_id=job.id)
    assert result["greeted"] == 2
    # 验证使用了岗位话术
    for sent in adapter.greetings_sent:
        assert sent["message"] in ["你好，请发简历", "您好，方便发简历吗"]


@pytest.mark.asyncio
async def test_auto_greet_no_adapter(db_session):
    service = BossAutomationService(db_session, adapter=None)
    result = await service.auto_greet()
    assert result["total_found"] == 0


def test_get_status(db_session):
    service = BossAutomationService(db_session)
    status = service.get_status()
    assert "adapter_type" in status
    assert "operations_today" in status
```

**test_router.py:**
```python
"""Boss 自动化 API 路由测试"""


def test_boss_status_api(client):
    resp = client.get("/api/boss/status")
    assert resp.status_code == 200
    assert resp.json()["adapter_type"] == "chrome_extension"
```

Register in main.py:
```python
from app.modules.boss_automation.router import router as boss_router
app.include_router(boss_router, prefix="/api/boss", tags=["boss_automation"])
```

Commit: `git commit -m "feat: add Boss automation service with greeting and resume collection"`

---

### Task 3: Chrome 插件

**Files:**
- Create: `chrome_extension/manifest.json`
- Create: `chrome_extension/popup.html`
- Create: `chrome_extension/popup.js`
- Create: `chrome_extension/content.js`
- Create: `chrome_extension/background.js`
- Create: `chrome_extension/styles.css`

**manifest.json:**
```json
{
  "manifest_version": 3,
  "name": "招聘助手 - Boss直聘",
  "version": "1.0.0",
  "description": "Boss直聘简历采集助手，自动采集候选人信息和简历",
  "permissions": ["activeTab", "storage", "downloads"],
  "host_permissions": ["https://www.zhipin.com/*"],
  "action": {
    "default_popup": "popup.html",
    "default_icon": {
      "16": "icons/icon16.png",
      "48": "icons/icon48.png",
      "128": "icons/icon128.png"
    }
  },
  "content_scripts": [
    {
      "matches": ["https://www.zhipin.com/*"],
      "js": ["content.js"],
      "css": ["styles.css"]
    }
  ],
  "background": {
    "service_worker": "background.js"
  }
}
```

**popup.html:**
```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <style>
    body { width: 320px; padding: 16px; font-family: -apple-system, "Microsoft YaHei", sans-serif; font-size: 14px; }
    h2 { margin: 0 0 12px; font-size: 16px; color: #333; }
    .status { padding: 8px 12px; border-radius: 6px; margin-bottom: 12px; font-size: 13px; }
    .status.ok { background: #e8f5e9; color: #2e7d32; }
    .status.error { background: #ffebee; color: #c62828; }
    .btn { display: block; width: 100%; padding: 10px; margin-bottom: 8px; border: none; border-radius: 6px; cursor: pointer; font-size: 14px; }
    .btn-primary { background: #1677ff; color: white; }
    .btn-primary:hover { background: #0958d9; }
    .btn-secondary { background: #f0f0f0; color: #333; }
    .btn-secondary:hover { background: #e0e0e0; }
    .btn:disabled { opacity: 0.5; cursor: not-allowed; }
    .result { margin-top: 12px; padding: 8px; background: #f5f5f5; border-radius: 4px; font-size: 12px; white-space: pre-wrap; }
    .settings { margin-top: 12px; }
    .settings label { display: block; margin-bottom: 4px; font-size: 12px; color: #666; }
    .settings input { width: 100%; padding: 6px; border: 1px solid #ddd; border-radius: 4px; box-sizing: border-box; margin-bottom: 8px; }
  </style>
</head>
<body>
  <h2>招聘助手</h2>
  <div id="status" class="status">检查连接中...</div>

  <div class="settings">
    <label>后端地址</label>
    <input type="text" id="serverUrl" value="http://127.0.0.1:8000" />
  </div>

  <button class="btn btn-primary" id="btnCollect">采集当前页面简历</button>
  <button class="btn btn-primary" id="btnBatchCollect">批量采集消息列表</button>
  <button class="btn btn-secondary" id="btnTest">测试连接</button>

  <div id="result" class="result" style="display:none;"></div>

  <script src="popup.js"></script>
</body>
</html>
```

**popup.js:**
```javascript
/**
 * 招聘助手 Chrome 插件 - Popup 界面逻辑
 */
const statusEl = document.getElementById('status');
const resultEl = document.getElementById('result');
const serverUrlInput = document.getElementById('serverUrl');

// 加载保存的服务器地址
chrome.storage.local.get(['serverUrl'], (data) => {
  if (data.serverUrl) serverUrlInput.value = data.serverUrl;
  checkConnection();
});

// 保存服务器地址
serverUrlInput.addEventListener('change', () => {
  chrome.storage.local.set({ serverUrl: serverUrlInput.value });
});

function getServerUrl() {
  return serverUrlInput.value.replace(/\/+$/, '');
}

async function checkConnection() {
  try {
    const resp = await fetch(`${getServerUrl()}/api/health`);
    const data = await resp.json();
    if (data.status === 'ok') {
      statusEl.className = 'status ok';
      statusEl.textContent = '已连接到招聘助手后端';
    } else {
      throw new Error('状态异常');
    }
  } catch (e) {
    statusEl.className = 'status error';
    statusEl.textContent = '未连接 - 请先启动招聘助手';
  }
}

function showResult(text) {
  resultEl.style.display = 'block';
  resultEl.textContent = text;
}

// 采集当前页面简历
document.getElementById('btnCollect').addEventListener('click', async () => {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    const results = await chrome.tabs.sendMessage(tab.id, { action: 'collectCurrentResume' });
    if (results && results.success) {
      // 发送到后端
      const resp = await fetch(`${getServerUrl()}/api/resumes/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(results.data),
      });
      if (resp.ok) {
        showResult(`采集成功：${results.data.name}`);
      } else if (resp.status === 409) {
        showResult(`已存在：${results.data.name}`);
      } else {
        showResult(`发送失败：${resp.statusText}`);
      }
    } else {
      showResult('未找到简历信息，请在候选人详情页使用');
    }
  } catch (e) {
    showResult(`错误：${e.message}`);
  }
});

// 批量采集
document.getElementById('btnBatchCollect').addEventListener('click', async () => {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    const results = await chrome.tabs.sendMessage(tab.id, { action: 'batchCollect' });
    if (results && results.success) {
      const resp = await fetch(`${getServerUrl()}/api/resumes/batch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(results.data),
      });
      const data = await resp.json();
      showResult(`批量采集完成\n新增：${data.created}\n重复：${data.duplicates}\n总计：${data.total}`);
    } else {
      showResult(results?.message || '批量采集失败');
    }
  } catch (e) {
    showResult(`错误：${e.message}`);
  }
});

// 测试连接
document.getElementById('btnTest').addEventListener('click', checkConnection);
```

**content.js:**
```javascript
/**
 * 招聘助手 - Content Script
 * 在 Boss 直聘页面上运行，提取候选人信息
 */

// 响应来自 popup 的消息
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === 'collectCurrentResume') {
    const data = collectCurrentResume();
    sendResponse(data);
  } else if (request.action === 'batchCollect') {
    const data = batchCollectFromList();
    sendResponse(data);
  }
  return true; // 保持消息通道开放
});

/**
 * 从当前候选人详情页/聊天页提取信息
 */
function collectCurrentResume() {
  try {
    // 尝试多种选择器适配 Boss 直聘页面结构
    const name = getText('.name, .user-name, .geek-name') || '';
    const phone = getText('.phone, [data-field="phone"]') || '';
    const email = getText('.email, [data-field="email"]') || '';
    const education = getText('.edu-info .text, .education') || '';
    const workYears = extractWorkYears(getText('.work-info .text, .work-years') || '');
    const salary = getText('.expect-salary, .salary') || '';
    const skills = getTextList('.skill-tag, .tag-item');
    const jobIntention = getText('.expect-job, .job-intention') || '';

    if (!name) {
      return { success: false, message: '未找到候选人姓名' };
    }

    return {
      success: true,
      data: {
        name,
        phone,
        email,
        education: normalizeEducation(education),
        work_years: workYears,
        expected_salary_min: parseSalaryMin(salary),
        expected_salary_max: parseSalaryMax(salary),
        job_intention: jobIntention,
        skills: skills.join(','),
        source: 'boss_zhipin',
      },
    };
  } catch (e) {
    return { success: false, message: e.message };
  }
}

/**
 * 从消息列表页批量采集
 */
function batchCollectFromList() {
  try {
    const items = document.querySelectorAll('.chat-item, .message-item, .candidate-item');
    if (items.length === 0) {
      return { success: false, message: '未找到候选人列表，请在消息列表页使用' };
    }

    const candidates = [];
    items.forEach((item) => {
      const name = item.querySelector('.name, .user-name')?.textContent?.trim() || '';
      if (name) {
        candidates.push({
          name,
          phone: '',
          email: '',
          source: 'boss_zhipin',
        });
      }
    });

    return { success: true, data: candidates };
  } catch (e) {
    return { success: false, message: e.message };
  }
}

// --- 工具函数 ---

function getText(selector) {
  const el = document.querySelector(selector);
  return el ? el.textContent.trim() : '';
}

function getTextList(selector) {
  return Array.from(document.querySelectorAll(selector)).map((el) => el.textContent.trim()).filter(Boolean);
}

function extractWorkYears(text) {
  const match = text.match(/(\d+)/);
  return match ? parseInt(match[1], 10) : 0;
}

function normalizeEducation(text) {
  if (text.includes('博士')) return '博士';
  if (text.includes('硕士')) return '硕士';
  if (text.includes('本科')) return '本科';
  if (text.includes('大专')) return '大专';
  return text;
}

function parseSalaryMin(text) {
  const match = text.match(/(\d+)/);
  return match ? parseInt(match[1], 10) * 1000 : 0;
}

function parseSalaryMax(text) {
  const parts = text.match(/(\d+)[-~](\d+)/);
  return parts ? parseInt(parts[2], 10) * 1000 : 0;
}
```

**background.js:**
```javascript
/**
 * 招聘助手 - Service Worker (Background)
 * 处理后台任务
 */

// 插件安装时初始化
chrome.runtime.onInstalled.addListener(() => {
  console.log('招聘助手插件已安装');
  chrome.storage.local.set({ serverUrl: 'http://127.0.0.1:8000' });
});
```

**styles.css:**
```css
/* 招聘助手注入到 Boss 直聘页面的样式 */
.recruitment-assistant-btn {
  position: fixed;
  bottom: 20px;
  right: 20px;
  z-index: 99999;
  padding: 10px 16px;
  background: #1677ff;
  color: white;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  font-size: 14px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
}
.recruitment-assistant-btn:hover {
  background: #0958d9;
}
```

Also create placeholder icons directory:
```bash
mkdir -p chrome_extension/icons
```

Commit: `git commit -m "feat: add Chrome extension for Boss Zhipin resume collection"`

---

### Task 4: IMAP 邮箱采集适配器

**Files:**
- Create: `app/adapters/email_receiver.py`
- Create: `tests/adapters/test_email_receiver.py`

**email_receiver.py:**
```python
"""IMAP 邮箱简历采集适配器

定时扫描 HR 邮箱，提取候选人发送的 PDF 简历附件。
"""
import email
import imaplib
import logging
import os
from email.header import decode_header
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)


class EmailReceiver:
    def __init__(self):
        self.host = settings.imap_host
        self.port = settings.imap_port
        self.user = settings.imap_user
        self.password = settings.imap_password

    def is_configured(self) -> bool:
        return bool(self.host and self.user and self.password)

    def fetch_new_resumes(self, save_dir: str = "") -> list[dict]:
        """扫描未读邮件，下载 PDF 附件

        Returns:
            [{"sender": "xxx@qq.com", "subject": "简历", "pdf_path": "/path/to/file.pdf"}, ...]
        """
        if not self.is_configured():
            logger.warning("IMAP 未配置")
            return []

        save_dir = save_dir or settings.resume_storage_path
        Path(save_dir).mkdir(parents=True, exist_ok=True)

        results = []
        try:
            mail = imaplib.IMAP4_SSL(self.host, self.port)
            mail.login(self.user, self.password)
            mail.select("INBOX")

            # 搜索未读邮件
            status, messages = mail.search(None, "UNSEEN")
            if status != "OK":
                return []

            for msg_id in messages[0].split():
                try:
                    status, msg_data = mail.fetch(msg_id, "(RFC822)")
                    if status != "OK":
                        continue

                    msg = email.message_from_bytes(msg_data[0][1])
                    sender = msg.get("From", "")
                    subject = self._decode_header(msg.get("Subject", ""))

                    # 遍历附件
                    for part in msg.walk():
                        if part.get_content_maintype() == "multipart":
                            continue
                        filename = part.get_filename()
                        if filename:
                            filename = self._decode_header(filename)
                            if filename.lower().endswith(".pdf"):
                                import time
                                safe_name = f"{int(time.time())}_{filename}"
                                filepath = os.path.join(save_dir, safe_name)
                                with open(filepath, "wb") as f:
                                    f.write(part.get_payload(decode=True))
                                results.append({
                                    "sender": sender,
                                    "subject": subject,
                                    "pdf_path": filepath,
                                })
                                logger.info(f"邮件简历已下载: {filename} from {sender}")
                except Exception as e:
                    logger.error(f"处理邮件 {msg_id} 失败: {e}")

            mail.logout()
        except Exception as e:
            logger.error(f"IMAP 连接失败: {e}")

        return results

    @staticmethod
    def _decode_header(header_value: str) -> str:
        """解码邮件头"""
        if not header_value:
            return ""
        parts = decode_header(header_value)
        decoded = []
        for content, charset in parts:
            if isinstance(content, bytes):
                decoded.append(content.decode(charset or "utf-8", errors="replace"))
            else:
                decoded.append(content)
        return "".join(decoded)
```

**test_email_receiver.py:**
```python
"""IMAP 邮箱采集测试（不连接真实邮箱）"""
from app.adapters.email_receiver import EmailReceiver


def test_email_receiver_not_configured():
    receiver = EmailReceiver()
    assert not receiver.is_configured()
    results = receiver.fetch_new_resumes()
    assert results == []


def test_decode_header():
    assert EmailReceiver._decode_header("") == ""
    assert EmailReceiver._decode_header("plain text") == "plain text"
```

Commit: `git commit -m "feat: add IMAP email receiver for resume PDF collection"`
