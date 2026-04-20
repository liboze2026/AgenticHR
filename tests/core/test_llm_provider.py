"""core.llm.provider — LLM call with retry + audit hooks."""
import pytest
import httpx
from unittest.mock import AsyncMock, patch

from app.core.llm.provider import LLMProvider, LLMError


def _mock_response(content: str, status: int = 200):
    resp = httpx.Response(
        status_code=status,
        json={"choices": [{"message": {"content": content}}]},
    )
    # httpx.Response.raise_for_status requires a linked request
    resp.request = httpx.Request("POST", "http://demo/chat/completions")
    return resp


@pytest.mark.asyncio
async def test_complete_success_single_try():
    mock_post = AsyncMock(return_value=_mock_response('{"ok": true}'))
    with patch("httpx.AsyncClient.post", mock_post):
        p = LLMProvider(api_key="k", base_url="http://demo", model="m")
        got = await p.complete(
            messages=[{"role": "user", "content": "hi"}],
            prompt_version="v1",
            f_stage="F1", entity_type="job", entity_id=1,
        )
    assert got == '{"ok": true}'
    assert mock_post.await_count == 1


@pytest.mark.asyncio
async def test_complete_retries_on_http_error():
    mock_post = AsyncMock(side_effect=[
        httpx.ConnectError("boom"),
        httpx.ConnectError("boom"),
        _mock_response('{"ok": 1}'),
    ])
    with patch("httpx.AsyncClient.post", mock_post):
        p = LLMProvider(api_key="k", base_url="http://demo", model="m",
                         max_retries=3, backoff_base=0.0)
        got = await p.complete(
            messages=[{"role": "user", "content": "hi"}],
            prompt_version="v1", f_stage="F1", entity_type="job", entity_id=1,
        )
    assert got == '{"ok": 1}'
    assert mock_post.await_count == 3


@pytest.mark.asyncio
async def test_complete_gives_up_after_max_retries():
    mock_post = AsyncMock(side_effect=httpx.ConnectError("boom"))
    with patch("httpx.AsyncClient.post", mock_post):
        p = LLMProvider(api_key="k", base_url="http://demo", model="m",
                         max_retries=3, backoff_base=0.0)
        with pytest.raises(LLMError):
            await p.complete(
                messages=[{"role": "user", "content": "hi"}],
                prompt_version="v1", f_stage="F1", entity_type="job", entity_id=1,
            )
    assert mock_post.await_count == 3


@pytest.mark.asyncio
async def test_complete_calls_audit_hook(monkeypatch):
    seen = []

    def fake_log(**kwargs):
        seen.append(kwargs)
        return "event-id"

    monkeypatch.setattr("app.core.llm.provider.log_event", fake_log)
    mock_post = AsyncMock(return_value=_mock_response('{"ok": 1}'))
    with patch("httpx.AsyncClient.post", mock_post):
        p = LLMProvider(api_key="k", base_url="http://demo", model="glm-4-flash")
        await p.complete(
            messages=[{"role": "user", "content": "hi"}],
            prompt_version="f1_v1",
            f_stage="F1_competency_review",
            entity_type="job", entity_id=42,
        )
    assert len(seen) == 1
    assert seen[0]["f_stage"] == "F1_competency_review"
    assert seen[0]["action"] == "llm_complete"
    assert seen[0]["entity_id"] == 42
    assert seen[0]["prompt_version"] == "f1_v1"
    assert seen[0]["model_name"] == "glm-4-flash"
