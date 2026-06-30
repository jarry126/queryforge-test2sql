"""有 RAG vs 无 RAG 执行准确率 A/B 对照（按难度分桶）.

对某个库的 CSpider dev 题目，同一批问题分别跑：
- RAG 路径：services.text2sql.run_query（完整链路：检索+重排+few-shot+自纠错）
- 无 RAG 路径：services.text2sql_norag.run_query_no_rag（整库 schema + 提示词，单次生成）
各自执行结果与 gold SQL 结果集比对，得 EX；按难度（easy/medium/hard/extra）分桶。

注意：student_assessment 在 CSpider dev 中无题，无法算 EX；请用有 gold 题的库
（concert_singer / world_1 / cre_Doc_Template_Mgt 等）。

运行：python -m eval.ab_eval --db concert_singer --limit 45
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
from app.services.text2sql_norag import run_query_no_rag
from eval.cspider_loader import load_examples
from eval.ex_eval import _gold_result, _normalize_rows
from eval.hardness import LEVELS, sql_hardness

REPORT_DIR = "eval/reports"


def _bucket() -> dict:
    return {lv: {"total": 0, "rag": 0, "norag": 0} for lv in LEVELS}


async def evaluate(db_id: str, limit: int, seed: int) -> dict:
    pool = [e for e in load_examples("dev") if e["db_id"] == db_id]
    if not pool:
        raise SystemExit(f"CSpider dev 中 db_id={db_id} 没有题目，换一个有 gold 的库（如 concert_singer）")
    random.seed(seed)
    examples = random.sample(pool, limit) if 0 < limit < len(pool) else pool

    buckets = _bucket()
    rag_ok = norag_ok = 0
    details = []

    for i, ex in enumerate(examples, 1):
        q, gold_sql = ex["question"], ex["query"]
        level = sql_hardness(gold_sql)
        buckets[level]["total"] += 1
        gold = await _gold_result(db_id, gold_sql)

        rag = await run_query(QueryRequest(question=q, db_id=db_id))
        norag = await run_query_no_rag(q, db_id)

        rag_m = gold is not None and rag.success and _normalize_rows(rag.rows) == gold
        norag_m = gold is not None and norag.success and _normalize_rows(norag.rows) == gold
        rag_ok += rag_m
        norag_ok += norag_m
        buckets[level]["rag"] += rag_m
        buckets[level]["norag"] += norag_m
        details.append({
            "level": level, "question": q, "gold_sql": gold_sql,
            "rag_sql": rag.sql, "rag_match": rag_m,
            "norag_sql": norag.sql, "norag_match": norag_m,
        })
        if i % 10 == 0:
            print(f"[{i}/{len(examples)}] RAG={rag_ok/i:.3f}  noRAG={norag_ok/i:.3f}")

    n = len(examples)
    summary = {
        "db_id": db_id, "total": n,
        "rag_ex": round(rag_ok / n, 4), "norag_ex": round(norag_ok / n, 4),
        "delta": round((rag_ok - norag_ok) / n, 4),
        "by_hardness": {
            lv: {
                "n": b["total"],
                "norag": round(b["norag"] / b["total"], 4) if b["total"] else None,
                "rag": round(b["rag"] / b["total"], 4) if b["total"] else None,
            }
            for lv, b in buckets.items()
        },
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    _print_table(summary)
    os.makedirs(REPORT_DIR, exist_ok=True)
    path = os.path.join(REPORT_DIR, f"ab_{db_id}_{int(time.time())}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "details": details}, f, ensure_ascii=False, indent=2)
    print(f"\n报告：{path}")
    return summary


def _print_table(s: dict) -> None:
    print(f"\n===== 有 RAG vs 无 RAG · db={s['db_id']} · {s['total']} 题 =====")
    print(f"{'难度':<8}{'题数':>5}{'无RAG':>9}{'有RAG':>9}{'差值':>9}")
    for lv in LEVELS:
        b = s["by_hardness"][lv]
        if not b["n"]:
            continue
        d = (b["rag"] or 0) - (b["norag"] or 0)
        print(f"{lv:<8}{b['n']:>5}{b['norag']:>9.3f}{b['rag']:>9.3f}{d:>+9.3f}")
    print(f"{'合计':<8}{s['total']:>5}{s['norag_ex']:>9.3f}{s['rag_ex']:>9.3f}{s['delta']:>+9.3f}")


async def main(db_id: str, limit: int, seed: int) -> None:
    if not settings.CSPIDER_DB_DIR:
        raise SystemExit("请在 .env 配置 CSPIDER_DB_DIR")
    await evaluate(db_id, limit, seed)
    await close_pool()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="concert_singer", help="目标库（须有 CSpider dev 题）")
    p.add_argument("--limit", type=int, default=50, help="随机采样条数；<=0 或 >该库题数则全测")
    p.add_argument("--seed", type=int, default=42, help="随机种子，保证可复现")
    args = p.parse_args()
    asyncio.run(main(args.db, args.limit, args.seed))
