"""LLM Provider: chat completion with retry + audit hook."""
import asyncio
import logging
import httpx

from app.config import settings
from app.core.audit.logger import log_event

logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """LLM 调用重试全败后抛. 调用方决定降级逻辑."""


class LLMProvider:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        max_retries: int = 3,
        backoff_base: float = 1.0,
        timeout: float = 60.0,
    ):
        self.api_key = api_key or settings.ai_api_key
        self.base_url = (base_url or settings.ai_base_url).rstrip("/")
        self.model = model or settings.ai_model
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.timeout = timeout

    def is_configured(self) -> bool:
        return bool(self.api_key and self.base_url and self.model)

    async def complete(
        self,
        messages: list[dict],
        *,
        prompt_version: str = "",
        f_stage: str = "",
        entity_type: str = "",
        entity_id: int | None = None,
        temperature: float = 0.2,
        response_format: str = "text",
    ) -> str:
        """返回 LLM 响应文本内容. 重试 max_retries 次后抛 LLMError."""
        body: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if response_format == "json":
            body["response_format"] = {"type": "json_object"}

        last_err: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(
                        f"{self.base_url}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json",
                        },
                        json=body,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"]

                log_event(
                    f_stage=f_stage or "unknown",
                    action="llm_complete",
                    entity_type=entity_type or "unknown",
                    entity_id=entity_id,
                    input_payload={"messages": messages, "temperature": temperature},
                    output_payload={"content": content},
                    prompt_version=prompt_version,
                    model_name=self.model,
                )
                return content

            except (httpx.HTTPError, KeyError, ValueError) as e:
                last_err = e
                logger.warning(
                    f"LLM complete attempt {attempt}/{self.max_retries} failed: {e}"
                )
                if attempt < self.max_retries:
                    await asyncio.sleep(self.backoff_base * (3 ** (attempt - 1)))

        log_event(
            f_stage=f_stage or "unknown",
            action="llm_complete_fail",
            entity_type=entity_type or "unknown",
            entity_id=entity_id,
            input_payload={"messages": messages},
            output_payload={"error": str(last_err)},
            prompt_version=prompt_version,
            model_name=self.model,
        )
        raise LLMError(f"LLM complete failed after {self.max_retries} retries: {last_err}")

    async def embed_batch(
        self,
        texts: list[str],
        *,
        embedding_model: str = "embedding-2",
    ) -> list[list[float]]:
        """批量 embedding. 空列表直接返回 []. 重试 max_retries 次后抛 LLMError."""
        if not texts:
            return []

        body = {"model": embedding_model, "input": texts}

        last_err: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(
                        f"{self.base_url}/embeddings",
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json",
                        },
                        json=body,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    items = sorted(data["data"], key=lambda x: x["index"])
                    return [item["embedding"] for item in items]
            except (httpx.HTTPError, KeyError, ValueError) as e:
                last_err = e
                logger.warning(f"embed_batch attempt {attempt} failed: {e}")
                if attempt < self.max_retries:
                    await asyncio.sleep(self.backoff_base * (3 ** (attempt - 1)))

        raise LLMError(f"embed_batch failed after {self.max_retries} retries: {last_err}")
