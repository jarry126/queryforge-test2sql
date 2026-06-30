"""RAG 消融实验：拆分 schema / rerank / few-shot / query expansion 的贡献.

默认不启用 SQL 自纠错重试（--retry 0），用于观察 RAG 组件本身的效果。

运行示例：
python -m eval.rag_ablation_eval --db concert_singer --limit 45
python -m eval.rag_ablation_eval --db cre_Doc_Template_Mgt --limit 50
python -m eval.rag_ablation_eval --limit 100
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import time
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from typing import Any

from app.core.cache import close_redis
from app.core.config import settings
from app.core.db import close_pool
from app.schemas.query import QueryRequest, QueryResponse
from app.services.text2sql import run_query
from eval.cspider_loader import load_examples
from eval.ex_eval import _gold_result, _normalize_rows
from eval.hardness import LEVELS, sql_hardness

REPORT_DIR = "eval/reports"


@dataclass(frozen=True)
class Variant:
    name: str
    query_expansion: bool
    rerank: bool
    fewshot_top_k: int
    doc_context: bool


VARIANTS = (
    Variant("schema_only", query_expansion=False, rerank=False, fewshot_top_k=0, doc_context=False),
    Variant("schema_rerank", query_expansion=False, rerank=True, fewshot_top_k=0, doc_context=False),
    Variant("schema_fewshot", query_expansion=False, rerank=True, fewshot_top_k=settings.FEWSHOT_TOP_K, doc_context=False),
    Variant(
        "schema_fewshot_expand",
        query_expansion=True,
        rerank=True,
        fewshot_top_k=settings.FEWSHOT_TOP_K,
        doc_context=False,
    ),
    Variant("full_rag", query_expansion=True, rerank=True, fewshot_top_k=settings.FEWSHOT_TOP_K, doc_context=True),
)


@contextmanager
def _temporary_setting(name: str, value: Any):
    old = getattr(settings, name)
    setattr(settings, name, value)
    try:
        yield
    finally:
        setattr(settings, name, old)


def _disable_eval_cache() -> None:
    settings.REDIS_ENABLED = False
    settings.SEMANTIC_CACHE_ENABLED = False
    settings.EVAL_SKIP_ANSWER_LLM = True


def _empty_buckets() -> dict[str, dict[str, int]]:
    return {lv: {v.name: 0 for v in VARIANTS} | {"total": 0} for lv in LEVELS}


def _match(resp: QueryResponse, gold: set | None) -> bool:
    return gold is not None and resp.success and _normalize_rows(resp.rows) == gold


async def _run_variant(question: str, db_id: str, variant: Variant, retry_count: int) -> QueryResponse:
    with _variant_settings(variant, retry_count):
        return await run_query(QueryRequest(question=question, db_id=db_id))


@contextmanager
def _variant_settings(variant: Variant, retry_count: int):
    with ExitStack() as stack:
        stack.enter_context(_temporary_setting("QUERY_EXPANSION_ENABLED", variant.query_expansion))
        stack.enter_context(_temporary_setting("RERANK_ENABLED", variant.rerank))
        stack.enter_context(_temporary_setting("FEWSHOT_TOP_K", variant.fewshot_top_k))
        stack.enter_context(_temporary_setting("DOC_CONTEXT_ENABLED", variant.doc_context))
        stack.enter_context(_temporary_setting("SQL_MAX_RETRY", retry_count))
        yield


def _pick_examples(db_id: str | None, limit: int, seed: int) -> list[dict]:
    pool = load_examples("dev")
    if db_id:
        pool = [e for e in pool if e["db_id"] == db_id]
        if not pool:
            raise SystemExit(f"CSpider dev 中 db_id={db_id} 没有题目")
    random.seed(seed)
    return random.sample(pool, limit) if 0 < limit < len(pool) else pool


async def _run_example_with_semaphore(
    sem: asyncio.Semaphore,
    idx: int,
    question: str,
    db_id: str,
) -> tuple[int, QueryResponse]:
    async with sem:
        return idx, await run_query(QueryRequest(question=question, db_id=db_id))


async def evaluate(db_id: str | None, limit: int, seed: int, retry_count: int, concurrency: int = 1) -> dict:
    _disable_eval_cache()
    examples = _pick_examples(db_id, limit, seed)
    buckets = _empty_buckets()
    correct = {v.name: 0 for v in VARIANTS}
    details: list[dict[str, Any]] = []
    prepared = []

    for ex in examples:
        q, gold_sql, item_db = ex["question"], ex["query"], ex["db_id"]
        level = sql_hardness(gold_sql, dialect=settings.SQL_DIALECT)
        buckets[level]["total"] += 1
        gold = await _gold_result(item_db, gold_sql)
        prepared.append((q, item_db, gold, level))
        details.append(
            {
                "db_id": item_db,
                "level": level,
                "question": q,
                "gold_sql": gold_sql,
            }
        )

    sem = asyncio.Semaphore(max(1, concurrency))
    total = len(examples)
    for variant in VARIANTS:
        done = 0
        with _variant_settings(variant, retry_count):
            tasks = [
                asyncio.create_task(_run_example_with_semaphore(sem, idx, q, item_db))
                for idx, (q, item_db, _gold, _level) in enumerate(prepared)
            ]
            for task in asyncio.as_completed(tasks):
                idx, resp = await task
                q, item_db, gold, level = prepared[idx]
                ok = _match(resp, gold)
                correct[variant.name] += int(ok)
                buckets[level][variant.name] += int(ok)
                row = details[idx]
                row[f"{variant.name}_sql"] = resp.sql
                row[f"{variant.name}_match"] = ok
                row[f"{variant.name}_attempts"] = resp.attempts
                row[f"{variant.name}_error"] = resp.error
                done += 1
                if done % 10 == 0 or done == total:
                    print(f"[{variant.name} {done}/{total}] acc={correct[variant.name] / done:.3f}")

        scores = "  ".join(f"{v.name}={correct[v.name] / total:.3f}" for v in VARIANTS if correct[v.name])
        print(f"[variant done] {variant.name}  {scores}")

    summary = {
        "db_id": db_id or "ALL",
        "split": "dev",
        "seed": seed,
        "total": total,
        "retry_count": retry_count,
        "concurrency": concurrency,
        "scores": {v.name: round(correct[v.name] / total, 4) if total else 0.0 for v in VARIANTS},
        "by_hardness": {
            lv: {
                "n": b["total"],
                **{v.name: round(b[v.name] / b["total"], 4) if b["total"] else None for v in VARIANTS},
            }
            for lv, b in buckets.items()
        },
        "variants": {
            v.name: {
                "query_expansion": v.query_expansion,
                "rerank": v.rerank,
                "fewshot_top_k": v.fewshot_top_k,
                "doc_context": v.doc_context,
            }
            for v in VARIANTS
        },
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    _print_table(summary)

    os.makedirs(REPORT_DIR, exist_ok=True)
    scope = db_id or "all"
    path = os.path.join(REPORT_DIR, f"rag_ablation_{scope}_{int(time.time())}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "details": details}, f, ensure_ascii=False, indent=2)
    print(f"\n报告：{path}")
    return summary


def _print_table(summary: dict) -> None:
    names = [v.name for v in VARIANTS]
    print(f"\n===== RAG 消融 · db={summary['db_id']} · {summary['total']} 题 =====")
    print(f"{'难度':<8}{'题数':>5}" + "".join(f"{name:>23}" for name in names))
    for lv in LEVELS:
        b = summary["by_hardness"][lv]
        if not b["n"]:
            continue
        print(f"{lv:<8}{b['n']:>5}" + "".join(f"{(b[name] or 0):>23.3f}" for name in names))
    scores = summary["scores"]
    print(f"{'合计':<8}{summary['total']:>5}" + "".join(f"{scores[name]:>23.3f}" for name in names))


async def main(db_id: str | None, limit: int, seed: int, retry_count: int, concurrency: int) -> None:
    if not settings.CSPIDER_DB_DIR:
        raise SystemExit("请在 .env 配置 CSPIDER_DB_DIR")
    await evaluate(db_id, limit, seed, retry_count, concurrency)
    await close_redis()
    await close_pool()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=None, help="目标库；不传则从 CSpider dev 全局随机抽样")
    parser.add_argument("--limit", type=int, default=50, help="样本数；<=0 或超过样本池则全量")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")
    parser.add_argument("--retry", type=int, default=0, help="SQL 自纠错重试次数；消融默认 0")
    parser.add_argument("--concurrency", type=int, default=1, help="题目级并发数；variant 仍逐个串行，避免配置串扰")
    args = parser.parse_args()
    asyncio.run(main(args.db, args.limit, args.seed, args.retry, args.concurrency))
