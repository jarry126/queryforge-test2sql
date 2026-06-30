"""CSpider 数据集加载.

读取 CSpider 的 tables.json / dev.json / train.json / *_gold.sql。
路径来自 settings.CSPIDER_ROOT（或显式传入）。
"""

from __future__ import annotations

import json
import os

from app.core.config import settings


def _root(root: str | None) -> str:
    r = root or settings.CSPIDER_ROOT
    if not r or not os.path.isdir(r):
        raise FileNotFoundError(f"CSPIDER_ROOT 无效: {r}（请在 .env 配置 CSPIDER_ROOT）")
    return r


def load_tables(root: str | None = None) -> dict[str, dict]:
    """返回 {db_id: schema_dict}。"""
    with open(os.path.join(_root(root), "tables.json"), encoding="utf-8") as f:
        data = json.load(f)
    return {item["db_id"]: item for item in data}


def load_examples(split: str = "dev", root: str | None = None) -> list[dict]:
    """返回样本列表，每个含 question / query / db_id。split: dev | train。"""
    with open(os.path.join(_root(root), f"{split}.json"), encoding="utf-8") as f:
        data = json.load(f)
    return [{"question": d["question"], "query": d["query"], "db_id": d["db_id"]} for d in data]
