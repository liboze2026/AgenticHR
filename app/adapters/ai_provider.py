"""AI 大模型适配器 - OpenAI 兼容接口"""
import json
import logging
import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class AIProvider:
    def __init__(self, api_key: str | None = None, base_url: str | None = None, model: str | None = None):
        self.api_key = api_key or settings.ai_api_key
        self.base_url = (base_url or settings.ai_base_url).rstrip("/")
        self.model = model or settings.ai_model

    async def evaluate_resume(self, resume_text: str, job_requirements: str) -> dict:
        prompt = f"""你是一个专业的HR简历筛选助手。请根据岗位要求评估以下简历。

## 岗位要求
{job_requirements}

## 候选人简历
{resume_text}

## 请输出以下JSON格式（不要输出其他内容）：
{{
    "score": <0-100的匹配度评分>,
    "strengths": ["优势点1", "优势点2", "优势点3"],
    "risks": ["风险点1", "风险点2"],
    "recommendation": "<推荐|待定|不推荐>",
    "summary": "<一句话综合评价>"
}}"""

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json={"model": self.model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.3},
                )
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0]
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0]
                return json.loads(content.strip())
        except Exception as e:
            logger.error(f"AI 评估失败: {e}")
            return {"score": -1, "strengths": [], "risks": [], "recommendation": "评估失败", "summary": f"AI 评估出错: {str(e)}"}

    def is_configured(self) -> bool:
        return bool(self.api_key and self.base_url and self.model)
