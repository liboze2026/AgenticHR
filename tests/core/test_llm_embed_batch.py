"""core.llm.provider.embed_batch — 批量 embedding."""
import pytest
import httpx
from unittest.mock import AsyncMock, patch

from app.core.llm.provider import LLMProvider, LLMError


def _embedding_response(vectors: list[list[float]], status: int = 200):
    resp = httpx.Response(
        status_code=status,
        json={"data": [{"embedding": v, "index": i} for i, v in enumerate(vectors)]},
    )
    resp.request = httpx.Request("POST", "http://demo/embeddings")
    return resp


@pytest.mark.asyncio
async def test_embed_batch_success():
    mock_post = AsyncMock(return_value=_embedding_response([[0.1, 0.2], [0.3, 0.4]]))
    with patch("httpx.AsyncClient.post", mock_post):
        p = LLMProvider(api_key="k", base_url="http://demo", model="m")
        got = await p.embed_batch(["Python", "Java"])
    assert len(got) == 2
    assert got[0] == [0.1, 0.2]
    assert got[1] == [0.3, 0.4]
    assert mock_post.await_count == 1


@pytest.mark.asyncio
async def test_embed_batch_empty_list():
    p = LLMProvider(api_key="k", base_url="http://demo", model="m")
    got = await p.embed_batch([])
    assert got == []


@pytest.mark.asyncio
async def test_embed_batch_retries_on_error():
    mock_post = AsyncMock(side_effect=[
        httpx.ConnectError("boom"),
        _embedding_response([[1.0]]),
    ])
    with patch("httpx.AsyncClient.post", mock_post):
        p = LLMProvider(api_key="k", base_url="http://demo", model="m",
                         max_retries=3, backoff_base=0.0)
        got = await p.embed_batch(["X"])
    assert got == [[1.0]]
    assert mock_post.await_count == 2


@pytest.mark.asyncio
async def test_embed_batch_fail_raises_llm_error():
    mock_post = AsyncMock(side_effect=httpx.ConnectError("boom"))
    with patch("httpx.AsyncClient.post", mock_post):
        p = LLMProvider(api_key="k", base_url="http://demo", model="m",
                         max_retries=2, backoff_base=0.0)
        with pytest.raises(LLMError):
            await p.embed_batch(["X"])
