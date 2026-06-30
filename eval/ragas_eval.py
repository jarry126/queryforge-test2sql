"""RAG 检索质量评测（ragas）.

对 CSpider dev 抽样：跑链路收集「检索到的上下文」与「最终回答」，
用 ragas 评估检索/生成质量：
- LLMContextPrecisionWithReference：检索上下文相对参考答案是否精准；
- LLMContextRecall：是否覆盖参考答案所需信息；
- Faithfulness：回答是否忠于检索内容；
- ResponseRelevancy：回答与问题的相关性。

参考答案（reference）：CSpider 的 gold SQL。
检索上下文（retrieved_contexts）：schema 文档 + 业务文档（doc_context）。
结果保存为 JSON 报告。

运行：python -m eval.ragas_eval --limit 50
依赖：pip install -e ".[eval]"；ragas 默认用 OpenAI 评审，需配置 key。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time

from app.core.db import close_pool, get_pool
from app.core.langgraph.graph import get_graph
from eval.cspider_loader import load_examples

REPORT_DIR = "eval/reports"


async def _collect_sample(db_id: str, question: str, gold_sql: str) -> dict:
    """跑链路并取回检索上下文与回答。"""
    graph = await get_graph()
    final = await graph.ainvoke(
        {"question": question, "db_id": db_id, "attempt": 0, "messages": []},
        config={"recursion_limit": 25},
    )
    contexts = [d["content"] for d in final.get("schema_docs", [])]
    contexts += [d["content"] for d in final.get("doc_context", [])]
    return {
        "user_input": question,
        "retrieved_contexts": contexts or ["（无检索结果）"],
        "response": final.get("answer", "") or "（无回答）",
        "reference": gold_sql,
    }


async def main(limit: int) -> None:
    await get_pool()
    examples = load_examples("dev")[:limit]
    samples = []
    for i, ex in enumerate(examples, 1):
        samples.append(await _collect_sample(ex["db_id"], ex["question"], ex["query"]))
        if i % 10 == 0:
            print(f"collected {i}/{len(examples)}")

    try:
        from ragas import EvaluationDataset, evaluate
        from ragas.metrics import (
            Faithfulness,
            LLMContextPrecisionWithReference,
            LLMContextRecall,
            ResponseRelevancy,
        )
    except ImportError as e:
        raise SystemExit("请先安装评测依赖: pip install -e '.[eval]'") from e

    dataset = EvaluationDataset.from_list(samples)
    result = evaluate(
        dataset=dataset,
        metrics=[
            LLMContextPrecisionWithReference(),
            LLMContextRecall(),
            Faithfulness(),
            ResponseRelevancy(),
        ],
    )

    scores = result.to_pandas().mean(numeric_only=True).round(4).to_dict()
    os.makedirs(REPORT_DIR, exist_ok=True)
    path = os.path.join(REPORT_DIR, f"ragas_dev_{int(time.time())}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"n": len(samples), "scores": scores}, f, ensure_ascii=False, indent=2)

    print("\n=== RAGAS 评测结果 ===")
    for k, v in scores.items():
        print(f"  {k}: {v}")
    print(f"报告: {path}")
    await close_pool()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=50)
    args = p.parse_args()
    asyncio.run(main(args.limit))
