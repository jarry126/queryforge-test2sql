"""混合检索 + RRF 融合.

对应手绘图①的「并发检索 → 去重剪枝 → 重排」：
1. 向量检索（pgvector）+ 关键词检索（pg_jieba）并发执行；
2. 用 Reciprocal Rank Fusion（RRF）融合两路排名；
3. 去重；
4. 交给 reranker 重排取 top_n。

schema 检索与 few-shot 检索复用同一套流程，只是目标表不同。
"""

from __future__ import annotations

import asyncio

from app.core.config import settings
from app.core.logging import logger
from app.core.metrics import retrieval_latency_seconds
from app.core.rag import keyword, reranker, vectorstore
from app.core.rag.embeddings import embed_query


async def _keyword_search(table: str, q: str, top_k: int, db_id: str | None) -> list[dict]:
    """按 RETRIEVAL_BACKEND 选择关键词后端；ES 失败时回退 pg_jieba。"""
    if settings.RETRIEVAL_BACKEND == "es":
        try:
            from app.core.rag import es_keyword

            return await es_keyword.keyword_search(table, q, top_k, db_id)
        except Exception as e:  # noqa: BLE001
            logger.warning("es_keyword_failed_fallback_pg", error=str(e))
    return await keyword.keyword_search(table, q, top_k, db_id)


def _rrf_fuse(ranked_lists: list[list[dict]], k: int) -> list[dict]:
    """RRF 融合多路排名结果。score = Σ 1/(k + rank)。按 id 去重。"""
    scores: dict[int, float] = {}
    docs: dict[int, dict] = {}
    for ranked in ranked_lists:
        for rank, doc in enumerate(ranked):
            did = doc["id"]
            scores[did] = scores.get(did, 0.0) + 1.0 / (k + rank + 1)
            docs.setdefault(did, doc)
    fused = []
    for did, score in sorted(scores.items(), key=lambda x: x[1], reverse=True):
        d = dict(docs[did])
        d["rrf_score"] = score
        fused.append(d)
    return fused


async def hybrid_search(
    table: str,
    queries: list[str],
    db_id: str | None = None,
    top_k: int | None = None,
    do_rerank: bool = True,
) -> list[dict]:
    """对一个或多个查询（多查询扩展）做混合检索并融合。

    参数：
        table: schema_doc | fewshot_example | rag_chunk
        queries: 改写后的问题 + 扩展的相似问（图①的 3 个问题并发检索）。
        do_rerank: 是否对融合结果做重排。
    """
    top_k = settings.RETRIEVE_TOP_K if top_k is None else top_k
    if top_k <= 0:
        return []
    primary = queries[0] if queries else ""

    async def _one(q: str) -> list[list[dict]]:
        emb = await embed_query(q)
        with retrieval_latency_seconds.labels(channel="vector").time():
            vec = await vectorstore.vector_search(table, emb, top_k, db_id)
        with retrieval_latency_seconds.labels(channel="keyword").time():
            kw = await _keyword_search(table, q, top_k, db_id)
        return [vec, kw]

    # 多查询 + 双通道并发
    results = await asyncio.gather(*[_one(q) for q in queries])
    ranked_lists = [lst for pair in results for lst in pair]
    fused = _rrf_fuse(ranked_lists, settings.RRF_K)[: top_k]

    if do_rerank and fused:
        fused = await reranker.rerank(primary, fused)
    return fused
