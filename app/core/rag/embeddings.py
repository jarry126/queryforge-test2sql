"""向量化（阿里云百炼 Qwen text-embedding，OpenAI 兼容接口）.

使用 DashScope 的 text-embedding-v4，经 OpenAI 兼容端点调用。
维度通过 dimensions 参数裁剪到 EMBEDDING_DIM，必须与建表/索引维度一致。
DashScope 单次批量有上限，按 EMBEDDING_BATCH_SIZE 分批请求。
"""

from __future__ import annotations

from functools import lru_cache

from openai import AsyncOpenAI

from app.core.config import settings
from app.core.resilience import dashscope_semaphore, get_breaker, retry_async


@lru_cache
def _client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=settings.DASHSCOPE_API_KEY, base_url=settings.EMBEDDING_BASE_URL)


@retry_async()
async def _embed_batch(texts: list[str]) -> list[list[float]]:
    resp = await _client().embeddings.create(
        model=settings.EMBEDDING_MODEL,
        input=texts,
        dimensions=settings.EMBEDDING_DIM,
    )
    return [d.embedding for d in resp.data]


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """批量向量化（按 DashScope 批量上限分批 + 熔断器 + 重试）。"""
    if not texts:
        return []
    out: list[list[float]] = []
    bs = max(1, settings.EMBEDDING_BATCH_SIZE)
    for i in range(0, len(texts), bs):
        batch = texts[i : i + bs]
        async with dashscope_semaphore():  # 并发闸，降低限流概率
            out.extend(await get_breaker("embedding").call(_embed_batch, batch))
    return out


async def embed_query(text: str) -> list[float]:
    """单条向量化。"""
    out = await embed_texts([text])
    return out[0]
