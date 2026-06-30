"""执行准确率（Execution Accuracy, EX）评测.

对 CSpider dev 抽样：用本服务链路生成 SQL，分别执行「预测 SQL」与「gold SQL」，
比较结果集是否一致（顺序无关的集合比较）。这是 text-to-SQL 的核心指标。

增强：
- 按难度（easy/medium/hard/extra）分桶统计 EX，定位复杂查询掉点；
- 错误样本单独落盘，便于人工归因。

运行：python -m eval.ex_eval --limit 100
注意：会真实调用 LLM，按 --limit 控制成本。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import time

from app.core.config import settings
from app.core.db import close_pool
from app.schemas.query import QueryRequest
from app.services.text2sql import run_query
from app.sql.executor import execute
from eval.cspider_loader import load_examples
from eval.hardness import LEVELS, sql_hardness

REPORT_DIR = "eval/reports"


def _normalize_rows(rows: list[list]) -> set:
    """把结果集转为可比较的集合（每行排序后转 tuple，规避列序差异）。"""
    return {tuple(sorted(map(str, r))) for r in rows}


async def _gold_result(db_id: str, gold_sql: str) -> set | None:
    res = await execute(db_id, gold_sql)
    return _normalize_rows(res.rows) if res.ok else None


async def evaluate(limit: int, split: str, seed: int) -> dict:
    settings.EVAL_SKIP_ANSWER_LLM = True
    # 随机采样（dev.json 按库分组排列，取前 N 会偏向最前面的库，故必须随机抽）
    pool = load_examples(split)
    random.seed(seed)
    examples = random.sample(pool, limit) if 0 < limit < len(pool) else pool
    total = len(examples)
    correct = 0
    gold_exec_fail = 0
    buckets = {lv: {"total": 0, "correct": 0} for lv in LEVELS}
    errors = []

    for i, ex in enumerate(examples, 1):
        level = sql_hardness(ex["query"], dialect=settings.SQL_DIALECT)
        buckets[level]["total"] += 1

        resp = await run_query(QueryRequest(question=ex["question"], db_id=ex["db_id"]))
        gold = await _gold_result(ex["db_id"], ex["query"])
        if gold is None:
            gold_exec_fail += 1
            match = False
        else:
            pred = _normalize_rows(resp.rows) if resp.success else None
            match = pred is not None and pred == gold

        correct += int(match)
        buckets[level]["correct"] += int(match)
        if not match:
            errors.append(
                {
                    "db_id": ex["db_id"],
                    "level": level,
                    "question": ex["question"],
                    "gold_sql": ex["query"],
                    "pred_sql": resp.sql,
                    "success": resp.success,
                    "error": resp.error,
                }
            )
        if i % 10 == 0:
            print(f"[{i}/{total}] EX={correct / i:.3f}")

    by_level = {
        lv: round(b["correct"] / b["total"], 4) if b["total"] else None
        for lv, b in buckets.items()
    }
    summary = {
        "split": split,
        "seed": seed,
        "total": total,
        "correct": correct,
        "execution_accuracy": round(correct / total, 4) if total else 0.0,
        "by_hardness": by_level,
        "hardness_counts": {lv: b["total"] for lv, b in buckets.items()},
        "gold_exec_fail": gold_exec_fail,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    os.makedirs(REPORT_DIR, exist_ok=True)
    ts = int(time.time())
    with open(os.path.join(REPORT_DIR, f"ex_{split}_{ts}.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    with open(os.path.join(REPORT_DIR, f"ex_{split}_{ts}_errors.json"), "w", encoding="utf-8") as f:
        json.dump(errors, f, ensure_ascii=False, indent=2)

    print(f"\nEX={summary['execution_accuracy']}  分桶={by_level}")
    print(f"报告: {REPORT_DIR}/ex_{split}_{ts}.json（错误样本 {len(errors)} 条已落盘）")
    return summary


async def main(limit: int, split: str, seed: int) -> None:
    if not settings.CSPIDER_DB_DIR:
        raise SystemExit("请在 .env 配置 CSPIDER_DB_DIR（sqlite 库目录）")
    await evaluate(limit, split, seed)
    await close_pool()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=100, help="随机采样条数；<=0 或 >全量则跑全量")
    p.add_argument("--split", default="dev")
    p.add_argument("--seed", type=int, default=42, help="随机种子，保证可复现")
    args = p.parse_args()
    asyncio.run(main(args.limit, args.split, args.seed))
