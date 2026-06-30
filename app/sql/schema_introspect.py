"""Schema 内省.

从 SQLite 文件反查 schema，转成与 CSpider tables.json 兼容的 dict，
使本服务也能对「未在 tables.json 中登记」的任意 sqlite 库工作（通用性）。
生产 postgres 库可在 Phase 2 增加 information_schema 内省。
"""

from __future__ import annotations

import os
import sqlite3


def introspect_sqlite(db_path: str, db_id: str) -> dict:
    """读取 sqlite schema，返回 CSpider 风格 schema dict。"""
    if not os.path.exists(db_path):
        raise FileNotFoundError(db_path)
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        table_names = [r[0] for r in cur.fetchall()]

        column_names_original: list[list] = [[-1, "*"]]
        column_types: list[str] = ["text"]
        primary_keys: list[int] = []
        foreign_keys: list[list[int]] = []
        col_index: dict[tuple[int, str], int] = {}

        for t_idx, tbl in enumerate(table_names):
            cur.execute(f"PRAGMA table_info('{tbl}')")
            for row in cur.fetchall():
                _cid, name, ctype, _notnull, _dflt, pk = row
                gi = len(column_names_original)
                column_names_original.append([t_idx, name])
                column_types.append(_norm_type(ctype))
                col_index[(t_idx, name.lower())] = gi
                if pk:
                    primary_keys.append(gi)

        # 外键
        for t_idx, tbl in enumerate(table_names):
            cur.execute(f"PRAGMA foreign_key_list('{tbl}')")
            for row in cur.fetchall():
                # row: id, seq, ref_table, from_col, to_col, ...
                ref_table = row[2]
                from_col = row[3]
                to_col = row[4]
                if ref_table not in table_names:
                    continue
                ref_idx = table_names.index(ref_table)
                a = col_index.get((t_idx, (from_col or "").lower()))
                b = col_index.get((ref_idx, (to_col or "").lower()))
                if a is not None and b is not None:
                    foreign_keys.append([a, b])

        return {
            "db_id": db_id,
            "table_names_original": table_names,
            "table_names": table_names,
            "column_names_original": column_names_original,
            "column_names": column_names_original,
            "column_types": column_types,
            "primary_keys": primary_keys,
            "foreign_keys": foreign_keys,
        }
    finally:
        conn.close()


def _norm_type(t: str) -> str:
    t = (t or "").lower()
    if any(k in t for k in ("int",)):
        return "number"
    if any(k in t for k in ("char", "text", "clob")):
        return "text"
    if any(k in t for k in ("real", "floa", "doub", "num", "dec")):
        return "number"
    if "date" in t or "time" in t:
        return "time"
    return "text"
