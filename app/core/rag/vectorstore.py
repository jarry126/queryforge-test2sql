"""pgvector 向量库操作.

提供 schema_doc / fewshot_example / rag_chunk 三张表的写入（带 embedding + tsv）
与向量近邻检索（cosine）。tsv 列在写入时用 pg_jieba 中文分词生成。
"""

from __future__ import annotations

from typing import Any

from app.core.db import get_pool
from app.core.rag.embeddings import embed_texts

# pg_jieba 提供的中文分词全文检索配置
JIEBA_CFG = "jiebacfg"


async def upsert_schema_docs(rows: list[dict]) -> int:
    """写入 schema 文档。每行需含 db_id, doc_type, table_name, content, metadata。"""
    if not rows:
        return 0
    embeddings = await embed_texts([r["content"] for r in rows])
    pool = await get_pool()
    async with pool.connection() as conn, conn.cursor() as cur:
        for r, emb in zip(rows, embeddings, strict=True):
            await cur.execute(
                f"""
                INSERT INTO schema_doc (db_id, doc_type, table_name, content, embedding, tsv, metadata)
                VALUES (%s, %s, %s, %s, %s, to_tsvector('{JIEBA_CFG}', %s), %s::jsonb)
                """,
                (
                    r["db_id"], r["doc_type"], r.get("table_name"), r["content"],
                    emb, r["content"], _json(r.get("metadata", {})),
                ),
            )
    return len(rows)


async def delete_schema_docs(db_id: str | None = None) -> int:
    """删除 schema_doc。评测/重灌 schema 语料时使用。"""
    pool = await get_pool()
    async with pool.connection() as conn, conn.cursor() as cur:
        if db_id:
            await cur.execute("DELETE FROM schema_doc WHERE db_id = %s", (db_id,))
        else:
            await cur.execute("DELETE FROM schema_doc")
        return cur.rowcount or 0


async def upsert_fewshots(rows: list[dict]) -> int:
    """写入 few-shot 示例。每行含 db_id, question, sql。向量基于 question。"""
    if not rows:
        return 0
    embeddings = await embed_texts([r["question"] for r in rows])
    pool = await get_pool()
    async with pool.connection() as conn, conn.cursor() as cur:
        for r, emb in zip(rows, embeddings, strict=True):
            await cur.execute(
                f"""
                INSERT INTO fewshot_example (db_id, question, sql, embedding, tsv)
                VALUES (%s, %s, %s, %s, to_tsvector('{JIEBA_CFG}', %s))
                """,
                (r["db_id"], r["question"], r["sql"], emb, r["question"]),
            )
    return len(rows)


async def upsert_rag_chunks(rows: list[dict]) -> list[int]:
    """写入业务文档块，返回插入后的 id 列表（供 summary 回填 chunk_id 集合）。

    每行含 doc_id, chunk_type, page, content, metadata。
    """
    if not rows:
        return []
    embeddings = await embed_texts([r["content"] for r in rows])
    ids: list[int] = []
    pool = await get_pool()
    async with pool.connection() as conn, conn.cursor() as cur:
        for r, emb in zip(rows, embeddings, strict=True):
            await cur.execute(
                f"""
                INSERT INTO rag_chunk (doc_id, chunk_type, page, content, embedding, tsv, metadata)
                VALUES (%s, %s, %s, %s, %s, to_tsvector('{JIEBA_CFG}', %s), %s::jsonb)
                RETURNING id
                """,
                (
                    r["doc_id"], r["chunk_type"], r.get("page"), r["content"],
                    emb, r["content"], _json(r.get("metadata", {})),
                ),
            )
            row = await cur.fetchone()
            ids.append(row[0])
    return ids


async def fetch_chunks_by_ids(ids: list[int]) -> list[dict]:
    """按 id 集合取回 rag_chunk 行（summary 展开用）。"""
    if not ids:
        return []
    pool = await get_pool()
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute("SELECT * FROM rag_chunk WHERE id = ANY(%s)", (ids,))
        cols = [c.name for c in cur.description]
        return [dict(zip(cols, row, strict=True)) for row in await cur.fetchall()]


async def vector_search(
    table: str, query_embedding: list[float], top_k: int, db_id: str | None = None
) -> list[dict]:
    """向量近邻检索（cosine 距离升序）。返回含 _vscore（相似度）的行。"""
    where = "WHERE db_id = %s" if db_id and table != "rag_chunk" else ""
    # 占位符顺序：SELECT(embedding) -> [WHERE(db_id)] -> ORDER BY(embedding) -> LIMIT(top_k)
    params: list[Any] = [query_embedding, *([db_id] if where else []), query_embedding, top_k]
    pool = await get_pool()
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            f"""
            SELECT *, 1 - (embedding <=> %s::vector) AS _vscore
            FROM {table}
            {where}
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            params,
        )
        cols = [c.name for c in cur.description]
        return [dict(zip(cols, row, strict=True)) for row in await cur.fetchall()]


def _json(obj: Any) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False)


async def fetch_full_schema(db_id: str) -> str:
    """取整库的完整 schema 文本（schema_doc 全量拼接，不做检索）。

    用于「无 RAG baseline」——直接把整库表结构喂给 LLM，对照 RAG 检索路径。
    库级概览排在最前，其余按 id 顺序。
    """
    pool = await get_pool()
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "SELECT content FROM schema_doc WHERE db_id = %s "
            "ORDER BY (doc_type = 'db') DESC, id",
            (db_id,),
        )
        rows = await cur.fetchall()
    return "\n\n".join(r[0] for r in rows)


async def count_schema_docs(db_id: str | None = None) -> int:
    pool = await get_pool()
    async with pool.connection() as conn, conn.cursor() as cur:
        if db_id:
            await cur.execute("SELECT count(*) FROM schema_doc WHERE db_id = %s", (db_id,))
        else:
            await cur.execute("SELECT count(*) FROM schema_doc")
        row = await cur.fetchone()
        return row[0] if row else 0
