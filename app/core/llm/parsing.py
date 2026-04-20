"""LLM JSON 响应解析 + Pydantic 校验. F1/F2/F3 共享."""
import json
from typing import TypeVar, Type

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


def extract_json(text: str) -> dict:
    """从 LLM 响应里抽出 JSON 对象.

    处理常见包装:
      - 裸 JSON: '{"a":1}'
      - ```json ... ``` 围栏
      - ``` ... ``` 裸围栏
      - 前后文字噪声 (贪婪匹配第一个 { 到最后一个 })

    失败抛 ValueError.
    """
    if not text:
        raise ValueError("empty input")

    s = text.strip()
    if "```json" in s:
        s = s.split("```json", 1)[1]
        if "```" in s:
            s = s.split("```", 1)[0]
    elif "```" in s:
        parts = s.split("```")
        if len(parts) >= 3:
            s = parts[1]
        else:
            s = parts[-1]
    s = s.strip()

    start = s.find("{")
    end = s.rfind("}")
    if start < 0 or end < 0 or end <= start:
        raise ValueError(f"no JSON object found in: {text[:120]!r}")
    candidate = s[start:end + 1]

    try:
        return json.loads(candidate)
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid JSON: {e}; got: {candidate[:120]!r}") from e


def parse_json_as(text: str, model_cls: Type[T]) -> T:
    """extract_json + Pydantic 校验. 失败抛 ValueError 或 ValidationError."""
    data = extract_json(text)
    return model_cls.model_validate(data)
