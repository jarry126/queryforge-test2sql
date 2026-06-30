"""用 LLM 生成可审核的 schema 表说明 JSON。

输出格式：
{
  "db_id": {
    "table_name": "xxx 表，用于记录 ...。字段 a 表示 ...，字段 b 表示 ...。"
  }
}

本脚本只写 JSON 文件，不修改数据库。审核后再用 eval.ingest_cspider 入库。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.core.db import close_pool
from app.services import llm
from eval.cspider_loader import load_tables

OUT_DIR = "eval/artifacts"


SYSTEM_PROMPT = """你是资深数据仓库建模专家，负责为 Text-to-SQL 系统编写数据字典。
请根据表名、列名、列中文名、字段类型和外键，判断每张表的业务含义。
要求：
1. 直接说明这张表是做什么的，不要写“相关信息”这种空话。
2. 解释关键缩写字段，例如 g=比赛场数、w=胜场、l=负场、rank=排名。
3. 如果无法确定，给出谨慎但具体的推断，并使用“可能”。
4. 每张表 1-3 句话，中文输出。
5. 只输出 JSON object，key 必须是原始 table_name，value 是中文表说明字符串。
"""


def _table_payload(schema: dict) -> list[dict[str, Any]]:
    tables = schema["table_names_original"]
    tables_readable = schema.get("table_names", tables)
    cols_orig = schema["column_names_original"]
    cols_readable = schema.get("column_names", cols_orig)
    types = schema.get("column_types", [])
    fk_pairs = schema.get("foreign_keys", [])
    out = []
    for tbl_idx, tbl_name in enumerate(tables):
        columns = []
        for i, (t_idx, col_name) in enumerate(cols_orig):
            if t_idx != tbl_idx:
                continue
            readable = cols_readable[i][1] if i < len(cols_readable) else col_name
            ctype = types[i] if i < len(types) else "text"
            columns.append({"name": col_name, "readable_name": readable, "type": ctype})
        foreign_keys = []
        for a, b in fk_pairs:
            if cols_orig[a][0] == tbl_idx:
                foreign_keys.append(
                    {
                        "column": cols_orig[a][1],
                        "ref_table": tables[cols_orig[b][0]],
                        "ref_column": cols_orig[b][1],
                    }
                )
        out.append(
            {
                "table_name": tbl_name,
                "readable_name": tables_readable[tbl_idx],
                "columns": columns,
                "foreign_keys": foreign_keys,
            }
        )
    return out


def _parse_json_object(text: str) -> dict[str, str]:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("LLM 返回的不是 JSON object")
    return {str(k): str(v).strip() for k, v in data.items() if str(v).strip()}


async def describe_db(db_id: str, schema: dict) -> dict[str, str]:
    payload = {
        "db_id": db_id,
        "tables": _table_payload(schema),
    }
    prompt = "请为下面数据库中的每张表生成表说明：\n" + json.dumps(payload, ensure_ascii=False, indent=2)
    raw = await llm.ainvoke([SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=prompt)], temperature=0, json_mode=True)
    descriptions = _parse_json_object(raw)
    expected = set(schema["table_names_original"])
    return {table: descriptions[table] for table in schema["table_names_original"] if table in descriptions and table in expected}


async def generate(db_ids: list[str] | None, output: str | None) -> str:
    tables = load_tables()
    selected = db_ids or sorted(tables)
    missing = [db_id for db_id in selected if db_id not in tables]
    if missing:
        raise SystemExit(f"CSpider tables.json 中不存在 db_id: {', '.join(missing)}")

    result: dict[str, dict[str, str]] = {}
    for i, db_id in enumerate(selected, 1):
        print(f"[{i}/{len(selected)}] describing {db_id}")
        result[db_id] = await describe_db(db_id, tables[db_id])

    os.makedirs(OUT_DIR, exist_ok=True)
    path = output or os.path.join(OUT_DIR, f"schema_descriptions_{int(time.time())}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n表说明已写入：{path}")
    return path


async def main(db_ids: list[str] | None, output: str | None) -> None:
    await generate(db_ids, output)
    await close_pool()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", action="append", default=None, help="指定 db_id；可重复传。不传则生成全部库")
    parser.add_argument("--output", default=None, help="输出 JSON 路径")
    args = parser.parse_args()
    asyncio.run(main(args.db, args.output))
