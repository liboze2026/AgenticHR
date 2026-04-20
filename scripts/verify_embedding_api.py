"""一次性验证智谱 /v1/embeddings API 兼容性.

跑法: python -m scripts.verify_embedding_api

预期输出:
  embedding dim = 1024 (embedding-2) 或 2048 (embedding-3)
  向量值 float, 前 5 个类似: [0.0012, -0.0085, 0.0234, ...]
"""
import asyncio
import os
import sys

from app.core.llm.provider import LLMProvider


async def main():
    if not os.environ.get("AI_API_KEY") and not os.path.exists(".env"):
        print("ERROR: 需要 .env 或环境变量 AI_API_KEY/AI_BASE_URL", file=sys.stderr)
        sys.exit(1)

    p = LLMProvider()
    if not p.is_configured():
        print(f"ERROR: LLMProvider 未配置. base={p.base_url} model={p.model}")
        sys.exit(1)

    vectors = await p.embed_batch(["Python", "Java", "测试"])
    for i, (name, vec) in enumerate(zip(["Python", "Java", "测试"], vectors)):
        print(f"[{i}] {name}: dim={len(vec)}, head={vec[:5]}")

    assert all(len(v) == len(vectors[0]) for v in vectors), "维度不一致!"
    print(f"✓ 维度一致 = {len(vectors[0])}")


if __name__ == "__main__":
    asyncio.run(main())
