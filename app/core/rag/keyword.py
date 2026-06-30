"""关键词检索（PostgreSQL 全文 + pg_jieba 中文分词）.

用 ts_rank_cd 作为 BM25 近似打分，与向量检索互补（混合检索的稀疏侧）。
ES 留到后期；当前在同库内用 pg_jieba 即可覆盖中文场景。
"""

from __future__ import annotations

from typing import Any

from app.core.db import get_pool

JIEBA_CFG = "jiebacfg"


async def keyword_search(table: str, query: str, top_k: int, db_id: str | None = None) -> list[dict]:
    """全文检索，返回含 _kscore（ts_rank_cd）的行（降序）。"""
    where_db = "AND db_id = %s" if db_id and table != "rag_chunk" else ""
    params: list[Any] = [query, query]  # tsv @@ query 用一次，ts_rank_cd 用一次
    if where_db:
        params.append(db_id)
    params.append(top_k)
    pool = await get_pool()
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            f"""
            SELECT *, ts_rank_cd(tsv, plainto_tsquery('{JIEBA_CFG}', %s)) AS _kscore
            FROM {table}
            WHERE tsv @@ plainto_tsquery('{JIEBA_CFG}', %s)
            {where_db}
            ORDER BY _kscore DESC
            LIMIT %s
            """,
            params,
        )
        cols = [c.name for c in cur.description]
        return [dict(zip(cols, row, strict=True)) for row in await cur.fetchall()]
