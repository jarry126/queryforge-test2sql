"""重排序（阿里云百炼 Qwen gte-rerank，DashScope 原生 API）.

对召回的候选做语义重排，取 top_n。对应手绘图①的「重排序」节点。
DashScope rerank 不是 OpenAI 兼容接口，用 httpx 调原生 REST 端点。
未配置 key / 未启用 / 调用失败时退化为原序返回（优雅降级 + 熔断保护）。
"""

from __future__ import annotations

import httpx

from app.core.config import settings
from app.core.logging import logger
from app.core.resilience import dashscope_semaphore, get_breaker, retry_async


@retry_async()
async def _rerank_once(query: str, docs: list[dict], top_n: int) -> list[dict]:
    headers = {
        "Authorization": f"Bearer {settings.DASHSCOPE_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.RERANK_MODEL,
        "input": {"query": query, "documents": [d["content"] for d in docs]},
        "parameters": {"return_documents": False, "top_n": min(top_n, len(docs))},
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(settings.RERANK_BASE_URL, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()

    out = []
    for item in data["output"]["results"]:
        d = dict(docs[item["index"]])
        d["rerank_score"] = item.get("relevance_score")
        out.append(d)
    return out


async def rerank(query: str, docs: list[dict], top_n: int | None = None) -> list[dict]:
    """对 docs（每个含 'content'）重排，返回带 rerank_score 的子集。

    熔断器保护 + 优雅降级：未启用 / 短路 / 调用失败时，原序返回前 top_n。
    """
    top_n = top_n or settings.RERANK_TOP_N
    if not docs:
        return []
    if not settings.RERANK_ENABLED or not settings.DASHSCOPE_API_KEY:
        return docs[:top_n]
    try:
        async with dashscope_semaphore():  # 并发闸，降低限流概率
            return await get_breaker("rerank").call(_rerank_once, query, docs, top_n)
    except Exception as e:  # noqa: BLE001
        logger.warning("rerank_failed_fallback", error=str(e))
        return docs[:top_n]
