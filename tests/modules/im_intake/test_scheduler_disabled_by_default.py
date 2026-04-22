"""F5 T13: F4 APScheduler defaults off unless F4_ENABLED=true."""
import pytest


def test_f4_enabled_defaults_false(monkeypatch):
    monkeypatch.delenv("F4_ENABLED", raising=False)
    from importlib import reload
    from app import config as cfg
    reload(cfg)
    assert cfg.settings.f4_enabled is False


def test_intake_scheduler_none_when_disabled(monkeypatch):
    monkeypatch.setenv("F4_ENABLED", "false")
    from importlib import reload
    from app import config as cfg
    reload(cfg)
    from app import main
    reload(main)
    assert getattr(main, "intake_scheduler", None) is None
