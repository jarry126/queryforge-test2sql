"""把 PostgreSQL 中的检索语料同步到 Elasticsearch（ES 作为 BM25 搜索镜像）.

为 schema_doc / fewshot_example / rag_chunk 建立 ES 索引并批量灌入，
_id 与 PG 主键一致，便于与向量检索结果用 RRF 融合。
content 字段使用中文分析器（默认 standard；生产建议装 analysis-smartcn 或 ik 插件）。

运行：python -m eval.sync_es
依赖：pip install -e ".[es]"，并将 .env 设 RETRIEVAL_BACKEND=es
"""

from __future__ import annotations

import asyncio

from app.core.config import settings
from app.core.db import close_pool, get_pool
from app.core.logging import logger
from app.core.rag.es_keyword import index_name

# 表 -> (content 来源列, 是否带 db_id)
TABLES = {
    "schema_doc": ("content", True),
    "fewshot_example": ("question", True),
    "rag_chunk": ("content", False),
}

ANALYZER = "standard"  # 装了 smartcn 插件可改 "smartcn"


def _mapping(with_db: bool) -> dict:
    props = {"content": {"type": "text", "analyzer": ANALYZER}}
    if with_db:
        props["db_id"] = {"type": "keyword"}
    return {"mappings": {"properties": props}}


async def _sync_table(es, table: str, content_col: str, with_db: bool) -> int:
    from elasticsearch.helpers import async_bulk

    idx = index_name(table)
    if await es.indices.exists(index=idx):
        await es.indices.delete(index=idx)
    await es.indices.create(index=idx, body=_mapping(with_db))

    cols = f"id, {content_col} AS content" + (", db_id" if with_db else "")
    pool = await get_pool()
    actions = []
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(f"SELECT {cols} FROM {table}")
        names = [c.name for c in cur.description]
        for row in await cur.fetchall():
            rec = dict(zip(names, row, strict=True))
            doc = {"content": rec["content"]}
            if with_db:
                doc["db_id"] = rec.get("db_id")
            actions.append({"_index": idx, "_id": rec["id"], "_source": doc})
    if actions:
        await async_bulk(es, actions)
    logger.info("es_synced", table=table, docs=len(actions), index=idx)
    return len(actions)


async def main() -> None:
    from elasticsearch import AsyncElasticsearch

    es = AsyncElasticsearch(hosts=[f"http://{settings.ES_HOST}:{settings.ES_PORT}"])
    try:
        total = 0
        for table, (col, with_db) in TABLES.items():
            total += await _sync_table(es, table, col, with_db)
        logger.info("es_sync_done", total=total)
    finally:
        await es.close()
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
