from unittest.mock import AsyncMock, MagicMock
import pytest
from app.adapters.boss.playwright_adapter import PlaywrightBossAdapter


def _mock_item(name, data_id, job=""):
    item = AsyncMock()
    name_el = AsyncMock(); name_el.inner_text = AsyncMock(return_value=name)
    job_el = AsyncMock(); job_el.inner_text = AsyncMock(return_value=job)
    item.query_selector.side_effect = lambda sel: {
        ".geek-name": name_el, ".source-job": job_el,
    }.get(sel)
    item.get_attribute = AsyncMock(return_value=data_id)
    return item


@pytest.mark.asyncio
async def test_list_chat_index_iterates_all_tabs():
    a = PlaywrightBossAdapter()
    page = AsyncMock()
    page.query_selector_all = AsyncMock(side_effect=[
        [_mock_item("张三", "id1", "前端"), _mock_item("李四", "id2", "后端")],
    ])
    page.goto = AsyncMock(); page.wait_for_selector = AsyncMock()
    a._page = page; a._random_delay = AsyncMock()
    a._switch_tab = AsyncMock(return_value=True)

    out = await a.list_chat_index()

    assert len(out) == 2
    assert out[0].boss_id == "id1" and out[0].name == "张三"
    a._switch_tab.assert_called_with("全部")


@pytest.mark.asyncio
async def test_send_message_types_and_clicks_send():
    a = PlaywrightBossAdapter()
    page = AsyncMock()
    input_el = AsyncMock(); send_btn = AsyncMock()
    page.query_selector = AsyncMock(side_effect=lambda sel: {
        f'.geek-item[data-id="bx"]': AsyncMock(),
        '#boss-chat-editor-input': input_el,
        '.submit-content .submit': send_btn,
    }.get(sel))
    page.wait_for_selector = AsyncMock()
    page.keyboard = MagicMock(); page.keyboard.type = AsyncMock()
    a._page = page; a._random_delay = AsyncMock()
    a._human_click = AsyncMock(); a._operations_today = 0

    ok = await a.send_message("bx", "你好")

    assert ok is True
    assert a._operations_today == 1
    send_btn.click.assert_called_once()


@pytest.mark.asyncio
async def test_list_received_resumes_returns_pdf_pairs():
    a = PlaywrightBossAdapter()
    page = AsyncMock()
    card = AsyncMock()
    card.get_attribute = AsyncMock(return_value="id99")
    btn = AsyncMock(); btn.get_attribute = AsyncMock(return_value="https://x/y.pdf")
    card.query_selector = AsyncMock(return_value=btn)
    page.query_selector_all = AsyncMock(return_value=[card])
    page.goto = AsyncMock()
    a._page = page; a._random_delay = AsyncMock()
    a._switch_tab = AsyncMock(return_value=True)

    out = await a.list_received_resumes()

    assert out == [("id99", "https://x/y.pdf")]
