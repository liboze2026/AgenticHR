"""Playwright Boss 直聘适配器

使用 Playwright 控制 Chrome 浏览器来操作 Boss 直聘网页，
具有反检测、随机延迟、人类行为模拟等特性。

真实页面结构（2026-04 验证）：
- 消息列表项: .geek-item (有 data-id 属性)
- 候选人姓名: .geek-name
- 职位: .source-job
- 最后消息: .push-text
- 时间: .time.time-shadow
- 标签栏: .chat-label-item (选中: .selected)
- 聊天区域: .chat-conversation
- 空状态: .conversation-no-data
"""
import asyncio
import logging
import random
import re
from pathlib import Path

from app.config import settings
from app.adapters.boss.base import BossAdapter, BossCandidate, BossMessage

logger = logging.getLogger(__name__)

try:
    from playwright.async_api import async_playwright, BrowserContext, Page
except ImportError:
    async_playwright = None  # type: ignore
    BrowserContext = None  # type: ignore
    Page = None  # type: ignore


class PlaywrightBossAdapter(BossAdapter):
    """通过 Playwright 操控 Chrome 浏览器的 Boss 直聘适配器"""

    BOSS_URL = "https://www.zhipin.com"
    CHAT_URL = "https://www.zhipin.com/web/boss/message"

    def __init__(
        self,
        user_data_dir: str = "./data/boss_browser",
        headless: bool = False,
        delay_min: float | None = None,
        delay_max: float | None = None,
    ):
        self.user_data_dir = user_data_dir
        self.headless = headless
        self.delay_min = delay_min or settings.boss_delay_min
        self.delay_max = delay_max or settings.boss_delay_max

        self._playwright = None
        self._browser: "BrowserContext | None" = None
        self._page: "Page | None" = None
        self._operations_today: int = 0

    # ── 生命周期 ──

    async def _ensure_browser(self):
        if self._page is not None:
            return

        if async_playwright is None:
            raise RuntimeError("playwright 未安装，请执行 pip install playwright && playwright install chromium")

        Path(self.user_data_dir).mkdir(parents=True, exist_ok=True)

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=self.user_data_dir,
            headless=self.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
            ignore_default_args=["--enable-automation"],
            locale="zh-CN",
            viewport={"width": 1280, "height": 800},
        )

        self._page = self._browser.pages[0] if self._browser.pages else await self._browser.new_page()

        await self._page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.chrome = { runtime: {} };
        """)

    async def close(self):
        if self._browser:
            await self._browser.close()
            self._browser = None
            self._page = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    # ── 人类行为模拟 ──

    async def _random_delay(self):
        delay = random.uniform(self.delay_min, self.delay_max)
        await asyncio.sleep(delay)

    async def _human_type(self, selector: str, text: str):
        await self._ensure_browser()
        assert self._page is not None
        await self._page.click(selector)
        for char in text:
            await self._page.keyboard.type(char, delay=random.randint(50, 200))

    async def _human_click(self, selector: str):
        await self._ensure_browser()
        assert self._page is not None
        element = await self._page.query_selector(selector)
        if element:
            box = await element.bounding_box()
            if box:
                x = box["x"] + box["width"] * random.uniform(0.3, 0.7)
                y = box["y"] + box["height"] * random.uniform(0.3, 0.7)
                await self._page.mouse.move(x, y, steps=random.randint(5, 15))
                await asyncio.sleep(random.uniform(0.1, 0.3))
                await self._page.mouse.click(x, y)
                return
        await self._page.click(selector)

    def _check_daily_limit(self):
        if self._operations_today >= settings.boss_max_operations_per_day:
            raise RuntimeError(f"已达到每日操作上限 {settings.boss_max_operations_per_day}")

    # ── 标签页切换 ──

    async def _switch_tab(self, tab_name: str):
        """切换到指定标签（如 '新招呼', '已获取简历'）"""
        await self._ensure_browser()
        assert self._page is not None

        tabs = await self._page.query_selector_all('.chat-label-item')
        for tab in tabs:
            text = await tab.inner_text()
            if tab_name in text:
                await tab.click()
                await self._random_delay()
                return True
        return False

    # ── BossAdapter 接口实现 ──

    async def get_new_greetings(self) -> list[BossCandidate]:
        """获取新的打招呼消息列表"""
        await self._ensure_browser()
        assert self._page is not None
        await self._random_delay()

        await self._page.goto(self.CHAT_URL, wait_until="networkidle")
        await self._random_delay()

        # 切换到"新招呼"标签
        await self._switch_tab("新招呼")

        candidates: list[BossCandidate] = []
        items = await self._page.query_selector_all(".geek-item")
        for item in items:
            name_el = await item.query_selector(".geek-name")
            name = await name_el.inner_text() if name_el else ""

            job_el = await item.query_selector(".source-job")
            job = await job_el.inner_text() if job_el else ""

            data_id = await item.get_attribute("data-id") or ""

            if name:
                candidates.append(BossCandidate(
                    name=name.strip(),
                    boss_id=data_id,
                    job_intention=job.strip(),
                ))

        logger.info(f"获取到 {len(candidates)} 个新招呼")
        return candidates

    async def send_greeting_reply(self, boss_id: str, message: str) -> bool:
        """点击候选人并发送打招呼回复"""
        self._check_daily_limit()
        await self._ensure_browser()
        assert self._page is not None
        await self._random_delay()

        try:
            # 点击候选人条目
            await self._human_click(f'.geek-item[data-id="{boss_id}"]')
            await self._random_delay()

            # 等待聊天区域加载
            await self._page.wait_for_selector('.chat-conversation', timeout=5000)

            # 查找并点击"求简历"按钮
            # 真实选择器: .operate-btn 文字为"求简历"
            operate_btns = await self._page.query_selector_all('.operate-btn')
            for btn in operate_btns:
                btn_text = await btn.inner_text()
                if '求简历' in btn_text:
                    await btn.click()
                    await self._random_delay()
                    # 可能弹出确认框，点击"确定"
                    confirm_btn = await self._page.query_selector('.exchange-tooltip .boss-btn-primary')
                    if confirm_btn:
                        await confirm_btn.click()
                    self._operations_today += 1
                    logger.info(f"已对 {boss_id} 点击求简历按钮")
                    return True

            # 如果没有"求简历"按钮，手动输入消息
            # 真实选择器: #boss-chat-editor-input (contenteditable div)
            input_sel = '#boss-chat-editor-input'
            input_el = await self._page.query_selector(input_sel)
            if input_el:
                await input_el.click()
                for char in message:
                    await self._page.keyboard.type(char, delay=random.randint(50, 150))
                    if random.random() < 0.1:
                        await asyncio.sleep(random.uniform(0.3, 0.8))

                await self._random_delay()

                send_btn = await self._page.query_selector(
                    '.submit-content .submit'
                )
                if send_btn:
                    await send_btn.click()
                    self._operations_today += 1
                    logger.info(f"已回复 {boss_id}")
                    return True

            return False
        except Exception as e:
            logger.error(f"回复消息失败 [{boss_id}]: {e}")
            return False

    async def get_candidate_info(self, boss_id: str) -> BossCandidate | None:
        """获取候选人详细信息（点击候选人后从右侧面板提取）"""
        await self._ensure_browser()
        assert self._page is not None
        await self._random_delay()

        try:
            # 点击候选人
            await self._human_click(f'.geek-item[data-id="{boss_id}"]')
            await self._random_delay()
            await self._page.wait_for_selector('.base-info-content', timeout=5000)

            # 姓名: .name-box
            name_el = await self._page.query_selector(".name-box")
            name = await name_el.inner_text() if name_el else ""

            # 基本信息: .base-info-single-detial > div
            # 顺序: 活跃状态(.active-time), 年龄, 工作年限/应届, 学历
            education = ""
            work_years = 0
            info_container = await self._page.query_selector('.base-info-single-detial')
            if info_container:
                divs = await info_container.query_selector_all(':scope > div')
                info_texts = []
                for div in divs:
                    cls = await div.get_attribute('class') or ''
                    if 'active-time' not in cls and 'name-contet' not in cls:
                        info_texts.append(await div.inner_text())
                # info_texts: [年龄, 工作年限, 学历]
                if len(info_texts) >= 3:
                    education = info_texts[2].strip()
                if len(info_texts) >= 2:
                    yr_text = info_texts[1]
                    yr_match = re.search(r'(\d+)\s*年', yr_text)
                    work_years = int(yr_match.group(1)) if yr_match else 0

            # 职位
            job_el = await self._page.query_selector('.position-content .position-name')
            job = await job_el.inner_text() if job_el else ""

            # 从 PDF 卡片提取联系方式
            pdf_title_el = await self._page.query_selector('.message-card-top-title')
            pdf_title = await pdf_title_el.inner_text() if pdf_title_el else ""
            phone_match = re.search(r'1[3-9]\d{9}', pdf_title)
            email_match = re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', pdf_title)

            return BossCandidate(
                name=name.strip(),
                boss_id=boss_id,
                education=education,
                work_years=work_years,
                job_intention=job.strip(),
                phone=phone_match.group() if phone_match else "",
                email=email_match.group() if email_match else "",
                has_pdf=bool(pdf_title_el),
            ) if name else None
        except Exception as e:
            logger.error(f"获取候选人信息失败 [{boss_id}]: {e}")
            return None

    async def get_chat_messages(self, boss_id: str) -> list[BossMessage]:
        """获取与候选人的聊天记录"""
        await self._ensure_browser()
        assert self._page is not None
        await self._random_delay()

        try:
            # 点击候选人
            await self._human_click(f'.geek-item[data-id="{boss_id}"]')
            await self._random_delay()
            await self._page.wait_for_selector('.chat-message-list', timeout=5000)

            messages: list[BossMessage] = []

            # 提取候选人发送的文字消息: .item-friend .text > span
            friend_msgs = await self._page.query_selector_all('.item-friend .text > span')
            for msg_el in friend_msgs:
                text = await msg_el.inner_text()
                messages.append(BossMessage(
                    sender_id=boss_id, sender_name="", content=text.strip(),
                    is_pdf=False, pdf_url="",
                ))

            # 提取 PDF 简历卡片: .message-card-wrap.boss-green
            pdf_cards = await self._page.query_selector_all('.message-card-wrap.boss-green')
            for card in pdf_cards:
                title_el = await card.query_selector('.message-card-top-title')
                title = await title_el.inner_text() if title_el else ""
                # PDF 预览按钮: .card-btn
                btn_el = await card.query_selector('.card-btn')
                pdf_url = ""
                if btn_el:
                    # 点击预览可能触发下载或打开预览页
                    pdf_url = await btn_el.get_attribute("href") or ""
                messages.append(BossMessage(
                    sender_id=boss_id, sender_name="", content=title.strip(),
                    is_pdf=True, pdf_url=pdf_url,
                ))

            return messages
        except Exception as e:
            logger.error(f"获取聊天记录失败 [{boss_id}]: {e}")
            return []

    async def download_pdf(self, pdf_url: str, save_path: str) -> bool:
        """下载候选人的 PDF 简历"""
        await self._ensure_browser()
        assert self._page is not None

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

    async def is_available(self) -> bool:
        if async_playwright is None:
            return False
        try:
            await self._ensure_browser()
            assert self._page is not None
            await self._page.goto(self.BOSS_URL, wait_until="domcontentloaded")
            login_btn = await self._page.query_selector(".btn-login, .login-btn")
            return login_btn is None
        except Exception:
            return False

    # ── F4-T8: chat index 扫描 / 发消息 / 求简历 / 已获取简历 ──

    async def list_chat_index(self) -> list[BossCandidate]:
        await self._ensure_browser()
        assert self._page is not None
        await self._random_delay()
        await self._page.goto(self.CHAT_URL, wait_until="networkidle")
        await self._random_delay()
        await self._switch_tab("全部")

        out: list[BossCandidate] = []
        items = await self._page.query_selector_all(".geek-item")
        for item in items:
            name_el = await item.query_selector(".geek-name")
            name = await name_el.inner_text() if name_el else ""
            job_el = await item.query_selector(".source-job")
            job = await job_el.inner_text() if job_el else ""
            data_id = await item.get_attribute("data-id") or ""
            if name:
                out.append(BossCandidate(
                    name=name.strip(), boss_id=data_id, job_intention=job.strip(),
                ))
        logger.info(f"list_chat_index: {len(out)} candidates")
        return out

    async def send_message(self, boss_id: str, text: str) -> bool:
        self._check_daily_limit()
        await self._ensure_browser()
        assert self._page is not None
        await self._random_delay()
        try:
            await self._human_click(f'.geek-item[data-id="{boss_id}"]')
            await self._random_delay()
            await self._page.wait_for_selector('.chat-conversation', timeout=5000)

            input_el = await self._page.query_selector('#boss-chat-editor-input')
            if not input_el:
                return False
            await input_el.click()
            for ch in text:
                await self._page.keyboard.type(ch, delay=random.randint(50, 150))
                if random.random() < 0.1:
                    await asyncio.sleep(random.uniform(0.3, 0.8))
            await self._random_delay()

            send_btn = await self._page.query_selector('.submit-content .submit')
            if not send_btn:
                return False
            await send_btn.click()
            self._operations_today += 1
            logger.info(f"send_message ok [{boss_id}]")
            return True
        except Exception as e:
            logger.error(f"send_message failed [{boss_id}]: {e}")
            return False

    async def click_request_resume(self, boss_id: str) -> bool:
        self._check_daily_limit()
        await self._ensure_browser()
        assert self._page is not None
        await self._random_delay()
        try:
            await self._human_click(f'.geek-item[data-id="{boss_id}"]')
            await self._random_delay()
            await self._page.wait_for_selector('.chat-conversation', timeout=5000)
            for btn in await self._page.query_selector_all('.operate-btn'):
                if '求简历' in (await btn.inner_text()):
                    await btn.click()
                    await self._random_delay()
                    confirm = await self._page.query_selector('.exchange-tooltip .boss-btn-primary')
                    if confirm:
                        await confirm.click()
                    self._operations_today += 1
                    return True
            return False
        except Exception as e:
            logger.error(f"click_request_resume failed [{boss_id}]: {e}")
            return False

    async def list_received_resumes(self) -> list[tuple[str, str]]:
        await self._ensure_browser()
        assert self._page is not None
        await self._random_delay()
        await self._page.goto(self.CHAT_URL, wait_until="networkidle")
        await self._switch_tab("已获取简历")
        await self._random_delay()
        out: list[tuple[str, str]] = []
        for card in await self._page.query_selector_all('.geek-item'):
            data_id = await card.get_attribute("data-id") or ""
            btn = await card.query_selector('.card-btn')
            if not btn:
                continue
            url = await btn.get_attribute("href") or ""
            if data_id and url:
                out.append((data_id, url))
        return out
