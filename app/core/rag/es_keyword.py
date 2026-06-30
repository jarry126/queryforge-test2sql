"""Elasticsearch BM25 关键词检索后端（pg_jieba 的可选替代）.

当 RETRIEVAL_BACKEND=es 时，混合检索的稀疏侧改用 Elasticsearch：
- ES 内建 BM25 与成熟的中文分析器（需在索引时配置 ik / smartcn analyzer）；
- 文档由 `eval/sync_es.py` 从 PostgreSQL 批量同步（ES 作为搜索镜像，id 与 PG 一致）。

返回结构与 `keyword.keyword_search` 对齐（含 id / content / _kscore），
使 retriever 可无缝切换后端。elasticsearch 客户端惰性导入，未装则报错由上层兜底。
"""

from __future__ import annotations

from functools import lru_cache

from app.core.config import settings


@lru_cache
def _client():
    from elasticsearch import AsyncElasticsearch

    return AsyncElasticsearch(hosts=[f"http://{settings.ES_HOST}:{settings.ES_PORT}"])


def index_name(table: str) -> str:
    return f"{settings.ES_INDEX_PREFIX}_{table}"


async def keyword_search(table: str, query: str, top_k: int, db_id: str | None = None) -> list[dict]:
    """ES BM25 检索，返回含 _kscore（_score）的行。"""
    must: list[dict] = [{"match": {"content": query}}]
    filt: list[dict] = []
    if db_id and table != "rag_chunk":
        filt.append({"term": {"db_id": db_id}})

    resp = await _client().search(
        index=index_name(table),
        size=top_k,
        query={"bool": {"must": must, "filter": filt}},
    )
    out = []
    for hit in resp["hits"]["hits"]:
        row = dict(hit["_source"])
        row["id"] = int(hit["_id"])
        row["_kscore"] = hit["_score"]
        out.append(row)
    return out
