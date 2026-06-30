"""Schema 文档风格对照实验。

对比 basic schema（原始表/列/外键）与 enriched schema（附加表语义描述）对准确率的影响。

注意：本脚本会反复清空并重灌 schema_doc；few-shot 表不会被修改。

运行示例：
python -m eval.schema_style_eval --db concert_singer --limit 45
python -m eval.schema_style_eval --limit 100
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time

from app.core.cache import close_redis
from app.core.config import settings
from app.core.db import close_pool
from eval.ingest_cspider import ingest_schemas, load_schema_descriptions
from eval.rag_ablation_eval import evaluate as evaluate_ablation

REPORT_DIR = "eval/reports"
STYLES = ("basic", "enriched")


async def evaluate(
    db_id: str | None,
    limit: int,
    seed: int,
    retry_count: int,
    keep_style: str,
    schema_descriptions: str,
    concurrency: int = 1,
) -> dict:
    settings.REDIS_ENABLED = False
    settings.SEMANTIC_CACHE_ENABLED = False
    settings.EVAL_SKIP_ANSWER_LLM = True

    descriptions = load_schema_descriptions(schema_descriptions)

    summaries = {}
    for style in STYLES:
        print(f"\n===== 重灌 schema_doc：{style} =====")
        await ingest_schemas(enriched=style == "enriched", replace=True, descriptions=descriptions)
        summaries[style] = await evaluate_ablation(db_id, limit, seed, retry_count, concurrency)

    if keep_style not in STYLES:
        keep_style = "enriched"
    print(f"\n===== 恢复 schema_doc：{keep_style} =====")
    await ingest_schemas(enriched=keep_style == "enriched", replace=True, descriptions=descriptions)

    result = {
        "db_id": db_id or "ALL",
        "limit": limit,
        "seed": seed,
        "retry_count": retry_count,
        "keep_style": keep_style,
        "schema_descriptions": schema_descriptions,
        "concurrency": concurrency,
        "scores": {style: summaries[style]["scores"] for style in STYLES},
        "by_hardness": {style: summaries[style]["by_hardness"] for style in STYLES},
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    os.makedirs(REPORT_DIR, exist_ok=True)
    scope = db_id or "all"
    path = os.path.join(REPORT_DIR, f"schema_style_{scope}_{int(time.time())}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\nSchema 风格对照报告：{path}")
    _print_delta(result)
    return result


def _print_delta(result: dict) -> None:
    print(f"\n===== Schema 风格对照 · db={result['db_id']} =====")
    basic = result["scores"]["basic"]
    enriched = result["scores"]["enriched"]
    for name, base_score in basic.items():
        new_score = enriched[name]
        print(f"{name:<24} basic={base_score:.3f}  enriched={new_score:.3f}  diff={new_score - base_score:+.3f}")


async def main(
    db_id: str | None,
    limit: int,
    seed: int,
    retry_count: int,
    keep_style: str,
    schema_descriptions: str | None,
    concurrency: int,
) -> None:
    if not settings.CSPIDER_DB_DIR:
        raise SystemExit("请在 .env 配置 CSPIDER_DB_DIR")
    if not schema_descriptions:
        raise SystemExit("请传 --schema-descriptions。没有真实表说明时，enriched schema 没有实验意义。")
    await evaluate(db_id, limit, seed, retry_count, keep_style, schema_descriptions, concurrency)
    await close_redis()
    await close_pool()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=None, help="目标库；不传则从 CSpider dev 全局随机抽样")
    parser.add_argument("--limit", type=int, default=50, help="样本数；<=0 或超过样本池则全量")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")
    parser.add_argument("--retry", type=int, default=0, help="SQL 自纠错重试次数")
    parser.add_argument("--keep-style", choices=["basic", "enriched"], default="enriched", help="实验结束后保留的 schema 风格")
    parser.add_argument("--schema-descriptions", default=None, help="表说明 JSON：{db_id: {table_name: description}}")
    parser.add_argument("--concurrency", type=int, default=1, help="题目级并发数；建议从 2 或 3 开始")
    args = parser.parse_args()
    asyncio.run(
        main(args.db, args.limit, args.seed, args.retry, args.keep_style, args.schema_descriptions, args.concurrency)
    )
