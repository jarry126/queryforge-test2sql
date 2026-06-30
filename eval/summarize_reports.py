"""汇总评测报告，生成文章/复盘可用的 Markdown 摘要.

只读取 eval/reports/*.json，不调用 LLM、不访问数据库。

运行：
python -m eval.summarize_reports \
  --reports eval/reports/fair_ab_concert_singer_xxx.json eval/reports/rag_ablation_concert_singer_xxx.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    data["_path"] = path
    return data


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def _print_scores(report: dict[str, Any]) -> None:
    summary = report["summary"]
    scores = summary.get("scores")
    if not scores:
        return
    print(f"\n## {Path(report['_path']).name}")
    print(f"\n- db: `{summary.get('db_id')}`")
    print(f"- total: `{summary.get('total')}`")
    print(f"- retry_count: `{summary.get('retry_count')}`")
    print("\n| Variant | EX |")
    print("|---|---:|")
    for name, score in scores.items():
        print(f"| `{name}` | {_fmt(score)} |")

    print("\n| Hardness | N | " + " | ".join(f"`{name}`" for name in scores) + " |")
    print("|---|---:|" + "|".join(["---:"] * len(scores)) + "|")
    for level, row in summary.get("by_hardness", {}).items():
        if not row.get("n"):
            continue
        vals = " | ".join(_fmt(row.get(name)) for name in scores)
        print(f"| {level} | {row['n']} | {vals} |")


def _variant_names(report: dict[str, Any]) -> list[str]:
    scores = report["summary"].get("scores", {})
    return list(scores)


def _print_pair_diff(report: dict[str, Any], left: str, right: str, max_cases: int) -> None:
    details = report.get("details", [])
    if not details or left not in _variant_names(report) or right not in _variant_names(report):
        return

    left_only = [d for d in details if d.get(f"{left}_match") and not d.get(f"{right}_match")]
    right_only = [d for d in details if d.get(f"{right}_match") and not d.get(f"{left}_match")]
    both_bad = [d for d in details if not d.get(f"{left}_match") and not d.get(f"{right}_match")]
    both_ok = [d for d in details if d.get(f"{left}_match") and d.get(f"{right}_match")]

    print(f"\n### `{left}` vs `{right}`")
    print(
        f"\n`both_ok={len(both_ok)}` · `{left}_only={len(left_only)}` · "
        f"`{right}_only={len(right_only)}` · `both_bad={len(both_bad)}`"
    )

    for label, rows in ((f"{right} wins", right_only), (f"{left} wins", left_only), ("both bad", both_bad)):
        if not rows:
            continue
        print(f"\n**{label}**")
        for d in rows[:max_cases]:
            print(f"\n- [{d.get('level')}] {d.get('question')}")
            print(f"  - gold: `{d.get('gold_sql')}`")
            print(f"  - {left}: `{d.get(f'{left}_sql')}`")
            print(f"  - {right}: `{d.get(f'{right}_sql')}`")


def _auto_pairs(report: dict[str, Any]) -> list[tuple[str, str]]:
    names = _variant_names(report)
    if {"noRAG_once", "RAG_once", "noRAG_retry", "RAG_retry"}.issubset(names):
        return [("noRAG_once", "RAG_once"), ("noRAG_retry", "RAG_retry"), ("RAG_once", "RAG_retry")]
    if {"schema_rerank", "schema_fewshot", "schema_fewshot_expand", "full_rag"}.issubset(names):
        return [
            ("schema_rerank", "schema_fewshot"),
            ("schema_fewshot", "schema_fewshot_expand"),
            ("schema_fewshot_expand", "full_rag"),
        ]
    return []


def main(paths: list[str], max_cases: int) -> None:
    reports = [_load(p) for p in paths]
    print("# Evaluation Summary")
    for report in reports:
        _print_scores(report)
        for left, right in _auto_pairs(report):
            _print_pair_diff(report, left, right, max_cases=max_cases)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reports", nargs="+", required=True, help="要汇总的报告 JSON 路径")
    parser.add_argument("--max-cases", type=int, default=3, help="每类差异最多展示多少条样本")
    args = parser.parse_args()
    main(args.reports, args.max_cases)
