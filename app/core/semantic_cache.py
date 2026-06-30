"""语义近似缓存（pgvector 相似问命中）.

Redis 精确缓存只命中字面相同的问题；语义缓存进一步命中「换种说法的同义问题」，
显著提升缓存命中率 —— 这是支撑 100 QPS 的关键之一（多数请求被缓存短路，绕开 LLM）。

策略：把 (db_id, 问题向量, 响应) 存入 query_cache；查询时对问题向量做近邻检索，
在同一 db_id、且 cosine 相似度 ≥ 阈值、且未过期时命中。
未启用 / 出错时降级为 miss。
"""

from __future__ import annotations

from app.core.config import settings
from app.core.db import get_pool
from app.core.logging import logger
from app.core.metrics import cache_total
from app.core.rag.embeddings import embed_query


async def get_semantic_cached(db_id: str, question: str) -> dict | None:
    """语义近邻命中则返回缓存响应，否则 None。"""
    if not settings.SEMANTIC_CACHE_ENABLED:
        return None
    try:
        emb = await embed_query(question)
        pool = await get_pool()
        async with pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                SELECT response, 1 - (embedding <=> %s::vector) AS sim
                FROM query_cache
                WHERE db_id = %s
                  AND created_at > now() - (%s || ' seconds')::interval
                ORDER BY embedding <=> %s::vector
                LIMIT 1
                """,
                (emb, db_id, settings.SEMANTIC_CACHE_TTL_SECONDS, emb),
            )
            row = await cur.fetchone()
    except Exception as e:  # noqa: BLE001
        logger.warning("semantic_cache_get_failed", error=str(e))
        return None

    if row and row[1] is not None and row[1] >= settings.SEMANTIC_CACHE_THRESHOLD:
        cache_total.labels(result="semantic_hit").inc()
        logger.info("semantic_cache_hit", db_id=db_id, sim=round(float(row[1]), 4))
        return row[0]
    cache_total.labels(result="semantic_miss").inc()
    return None


async def set_semantic_cached(db_id: str, question: str, payload: dict) -> None:
    """写入语义缓存（仅成功结果调用）。"""
    if not settings.SEMANTIC_CACHE_ENABLED:
        return
    try:
        emb = await embed_query(question)
        pool = await get_pool()
        async with pool.connection() as conn, conn.cursor() as cur:
            import json

            await cur.execute(
                "INSERT INTO query_cache (db_id, question, embedding, response) VALUES (%s, %s, %s, %s::jsonb)",
                (db_id, question, emb, json.dumps(payload, ensure_ascii=False)),
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("semantic_cache_set_failed", error=str(e))
