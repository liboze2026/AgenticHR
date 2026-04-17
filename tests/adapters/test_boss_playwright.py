"""Playwright Boss 适配器测试

验证接口合规性、方法完整性和默认配置，不启动浏览器。
"""
import inspect

from app.adapters.boss.base import BossAdapter
from app.adapters.boss.playwright_adapter import PlaywrightBossAdapter
from app.config import settings


def test_playwright_adapter_is_subclass():
    """PlaywrightBossAdapter 是 BossAdapter 的子类"""
    assert issubclass(PlaywrightBossAdapter, BossAdapter)


def test_playwright_adapter_has_all_required_methods():
    """适配器实现了所有抽象方法"""
    abstract_methods = set()
    for name, method in inspect.getmembers(BossAdapter, predicate=inspect.isfunction):
        if getattr(method, "__isabstractmethod__", False):
            abstract_methods.add(name)

    adapter_methods = {name for name, _ in inspect.getmembers(
        PlaywrightBossAdapter, predicate=inspect.isfunction
    )}

    for method_name in abstract_methods:
        assert method_name in adapter_methods, f"缺少方法: {method_name}"


def test_playwright_adapter_default_config():
    """默认配置值来自 settings"""
    adapter = PlaywrightBossAdapter()
    assert adapter.delay_min == settings.boss_delay_min
    assert adapter.delay_max == settings.boss_delay_max
    assert adapter.headless is False
    assert adapter.user_data_dir == "./data/boss_browser"


def test_playwright_adapter_custom_config():
    """支持自定义配置"""
    adapter = PlaywrightBossAdapter(
        user_data_dir="/tmp/test_browser",
        headless=True,
        delay_min=1.0,
        delay_max=2.0,
    )
    assert adapter.delay_min == 1.0
    assert adapter.delay_max == 2.0
    assert adapter.headless is True
    assert adapter.user_data_dir == "/tmp/test_browser"


def test_playwright_adapter_has_close_method():
    """适配器有 close 方法"""
    adapter = PlaywrightBossAdapter()
    assert hasattr(adapter, "close")
    assert callable(adapter.close)
