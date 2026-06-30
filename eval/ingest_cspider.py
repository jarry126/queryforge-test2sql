"""把 CSpider 灌进 RAG 库.

- 对 tables.json 每个库构建 schema 文档写入 schema_doc（pgvector + pg_jieba tsv）；
- 从 train.json 抽取 (question -> query) 作为 few-shot 写入 fewshot_example。

运行：python -m eval.ingest_cspider [--fewshot-limit 2000]
"""

from __future__ import annotations

import argparse
import asyncio
import json

from app.core.db import close_pool
from app.core.logging import logger
from app.core.rag.schema_corpus import build_schema_docs
from app.core.rag.vectorstore import count_schema_docs, delete_schema_docs, upsert_fewshots, upsert_schema_docs
from eval.cspider_loader import load_examples, load_tables


def load_schema_descriptions(path: str | None) -> dict[str, dict[str, str]]:
    """读取 {db_id: {table_name: description}} 格式的表说明。"""
    if not path:
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("schema descriptions 必须是 JSON object")
    return data


async def ingest_schemas(
    enriched: bool = False,
    replace: bool = False,
    descriptions: dict[str, dict[str, str]] | None = None,
) -> int:
    tables = load_tables()
    if replace:
        deleted = await delete_schema_docs()
        logger.warning("schema_doc_replaced", deleted=deleted)
    total = 0
    descriptions = descriptions or {}
    for db_id, schema in tables.items():
        docs = build_schema_docs(schema, enriched=enriched, descriptions=descriptions.get(db_id))
        total += await upsert_schema_docs(docs)
        logger.info(
            "schema_ingested",
            db_id=db_id,
            docs=len(docs),
            enriched=enriched,
            descriptions=len(descriptions.get(db_id, {})),
        )
    return total


async def ingest_fewshots(limit: int) -> int:
    examples = load_examples("train")[:limit]
    rows = [{"db_id": e["db_id"], "question": e["question"], "sql": e["query"]} for e in examples]
    # 分批写，避免单次 embedding 请求过大
    total = 0
    batch = 100
    for i in range(0, len(rows), batch):
        total += await upsert_fewshots(rows[i : i + batch])
        logger.info("fewshot_batch", done=min(i + batch, len(rows)), of=len(rows))
    return total


async def main(
    fewshot_limit: int,
    schema_style: str,
    replace_schemas: bool,
    skip_fewshots: bool,
    schema_descriptions: str | None,
) -> None:
    existing = await count_schema_docs()
    if existing and not replace_schemas:
        logger.warning("schema_doc_not_empty", count=existing, hint="重复运行会追加，建议先清表")
    descriptions = load_schema_descriptions(schema_descriptions)
    n_schema = await ingest_schemas(
        enriched=schema_style == "enriched",
        replace=replace_schemas,
        descriptions=descriptions,
    )
    n_few = 0 if skip_fewshots else await ingest_fewshots(fewshot_limit)
    logger.info("ingest_done", schema_docs=n_schema, fewshots=n_few, schema_style=schema_style)
    await close_pool()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fewshot-limit", type=int, default=2000, help="few-shot 写入条数上限")
    parser.add_argument("--schema-style", choices=["basic", "enriched"], default="basic", help="schema_doc 内容风格")
    parser.add_argument("--replace-schemas", action="store_true", help="写入前清空 schema_doc，避免新旧 schema 混在一起")
    parser.add_argument("--skip-fewshots", action="store_true", help="只重灌 schema_doc，不重复写入 few-shot")
    parser.add_argument("--schema-descriptions", default=None, help="表说明 JSON：{db_id: {table_name: description}}")
    args = parser.parse_args()
    asyncio.run(
        main(
            args.fewshot_limit,
            args.schema_style,
            args.replace_schemas,
            args.skip_fewshots,
            args.schema_descriptions,
        )
    )
