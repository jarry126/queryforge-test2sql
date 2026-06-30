"""公平 A/B：拆分 RAG 与 SQL 自纠错重试的贡献.

同一批 CSpider dev 样本跑四组：
- noRAG_once：完整 schema + 单次生成
- noRAG_retry：完整 schema + 校验/执行失败自纠错
- RAG_once：RAG 链路 + 单次生成
- RAG_retry：RAG 链路 + 自纠错

运行示例：
python -m eval.fair_ab_eval --db concert_singer --limit 45
python -m eval.fair_ab_eval --limit 100
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import time
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from typing import Any

from app.core.cache import close_redis
from app.core.config import settings
from app.core.db import close_pool
from app.schemas.query import QueryRequest, QueryResponse
from app.services.text2sql import run_query
from app.services.text2sql_norag import run_query_no_rag
from eval.cspider_loader import load_examples
from eval.ex_eval import _gold_result, _normalize_rows
from eval.hardness import LEVELS, sql_hardness

REPORT_DIR = "eval/reports"
VARIANTS = ("noRAG_once", "noRAG_retry", "RAG_once", "RAG_retry")


@contextmanager
def _temporary_setting(name: str, value: Any):
    old = getattr(settings, name)
    setattr(settings, name, value)
    try:
        yield
    finally:
        setattr(settings, name, old)


def _disable_eval_cache() -> None:
    """评测必须走真实生成链路，避免 Redis/语义缓存污染结果。"""
    settings.REDIS_ENABLED = False
    settings.SEMANTIC_CACHE_ENABLED = False
    settings.EVAL_SKIP_ANSWER_LLM = True


def _empty_buckets() -> dict[str, dict[str, int]]:
    return {lv: {v: 0 for v in VARIANTS} | {"total": 0} for lv in LEVELS}


def _match(resp: QueryResponse, gold: set | None) -> bool:
    return gold is not None and resp.success and _normalize_rows(resp.rows) == gold


async def _run_rag(question: str, db_id: str, max_retries: int) -> QueryResponse:
    with _temporary_setting("SQL_MAX_RETRY", max_retries):
        return await run_query(QueryRequest(question=question, db_id=db_id))


async def _run_variants(question: str, db_id: str, retry_count: int) -> dict[str, QueryResponse]:
    runners: dict[str, Callable[[], Awaitable[QueryResponse]]] = {
        "noRAG_once": lambda: run_query_no_rag(question, db_id, max_retries=0),
        "noRAG_retry": lambda: run_query_no_rag(question, db_id, max_retries=retry_count),
        "RAG_once": lambda: _run_rag(question, db_id, max_retries=0),
        "RAG_retry": lambda: _run_rag(question, db_id, max_retries=retry_count),
    }
    out: dict[str, QueryResponse] = {}
    for name, runner in runners.items():
        out[name] = await runner()
    return out


def _pick_examples(db_id: str | None, limit: int, seed: int) -> list[dict]:
    pool = load_examples("dev")
    if db_id:
        pool = [e for e in pool if e["db_id"] == db_id]
        if not pool:
            raise SystemExit(f"CSpider dev 中 db_id={db_id} 没有题目")
    random.seed(seed)
    return random.sample(pool, limit) if 0 < limit < len(pool) else pool


async def evaluate(db_id: str | None, limit: int, seed: int, retry_count: int) -> dict:
    _disable_eval_cache()
    examples = _pick_examples(db_id, limit, seed)
    buckets = _empty_buckets()
    correct = {v: 0 for v in VARIANTS}
    details = []

    for i, ex in enumerate(examples, 1):
        q, gold_sql, item_db = ex["question"], ex["query"], ex["db_id"]
        level = sql_hardness(gold_sql, dialect=settings.SQL_DIALECT)
        buckets[level]["total"] += 1
        gold = await _gold_result(item_db, gold_sql)
        responses = await _run_variants(q, item_db, retry_count)

        row: dict[str, Any] = {
            "db_id": item_db,
            "level": level,
            "question": q,
            "gold_sql": gold_sql,
        }
        for name, resp in responses.items():
            ok = _match(resp, gold)
            correct[name] += int(ok)
            buckets[level][name] += int(ok)
            row[f"{name}_sql"] = resp.sql
            row[f"{name}_match"] = ok
            row[f"{name}_attempts"] = resp.attempts
            row[f"{name}_error"] = resp.error
        details.append(row)

        if i % 10 == 0 or i == len(examples):
            scores = "  ".join(f"{v}={correct[v] / i:.3f}" for v in VARIANTS)
            print(f"[{i}/{len(examples)}] {scores}")

    total = len(examples)
    summary = {
        "db_id": db_id or "ALL",
        "split": "dev",
        "seed": seed,
        "total": total,
        "retry_count": retry_count,
        "scores": {v: round(correct[v] / total, 4) if total else 0.0 for v in VARIANTS},
        "by_hardness": {
            lv: {
                "n": b["total"],
                **{v: round(b[v] / b["total"], 4) if b["total"] else None for v in VARIANTS},
            }
            for lv, b in buckets.items()
        },
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    _print_table(summary)

    os.makedirs(REPORT_DIR, exist_ok=True)
    scope = db_id or "all"
    path = os.path.join(REPORT_DIR, f"fair_ab_{scope}_{int(time.time())}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "details": details}, f, ensure_ascii=False, indent=2)
    print(f"\n报告：{path}")
    return summary


def _print_table(summary: dict) -> None:
    print(f"\n===== 公平 A/B · db={summary['db_id']} · {summary['total']} 题 =====")
    print(f"{'难度':<8}{'题数':>5}" + "".join(f"{v:>14}" for v in VARIANTS))
    for lv in LEVELS:
        b = summary["by_hardness"][lv]
        if not b["n"]:
            continue
        print(f"{lv:<8}{b['n']:>5}" + "".join(f"{(b[v] or 0):>14.3f}" for v in VARIANTS))
    scores = summary["scores"]
    print(f"{'合计':<8}{summary['total']:>5}" + "".join(f"{scores[v]:>14.3f}" for v in VARIANTS))


async def main(db_id: str | None, limit: int, seed: int, retry_count: int) -> None:
    if not settings.CSPIDER_DB_DIR:
        raise SystemExit("请在 .env 配置 CSPIDER_DB_DIR")
    await evaluate(db_id, limit, seed, retry_count)
    await close_redis()
    await close_pool()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=None, help="目标库；不传则从 CSpider dev 全局随机抽样")
    parser.add_argument("--limit", type=int, default=50, help="样本数；<=0 或超过样本池则全量")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")
    parser.add_argument("--retry", type=int, default=settings.SQL_MAX_RETRY, help="重试次数")
    args = parser.parse_args()
    asyncio.run(main(args.db, args.limit, args.seed, args.retry))
