"""端到端冒烟：对 CSpider dev 抽样跑链路，检查链路不报错、SQL 可执行。

运行：python -m scripts.smoke_query --limit 20
"""

from __future__ import annotations

import argparse
import asyncio
import random

from app.core.db import close_pool
from app.schemas.query import QueryRequest
from app.services.text2sql import run_query
from eval.cspider_loader import load_examples


async def main(limit: int, seed: int) -> None:
    examples = load_examples("dev")
    random.seed(seed)
    sample = random.sample(examples, min(limit, len(examples)))

    ok = 0
    for i, ex in enumerate(sample, 1):
        resp = await run_query(QueryRequest(question=ex["question"], db_id=ex["db_id"]))
        status = "✓" if resp.success else "✗"
        ok += int(resp.success)
        print(f"[{i}/{len(sample)}] {status} db={ex['db_id']}")
        print(f"    Q: {ex['question']}")
        print(f"    预测 SQL: {resp.sql}")
        print(f"    gold SQL: {ex['query']}")
        if not resp.success:
            print(f"    错误: {resp.error}")
    print(f"\n冒烟通过率: {ok}/{len(sample)} = {ok / len(sample):.2%}")
    await close_pool()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()
    asyncio.run(main(args.limit, args.seed))
