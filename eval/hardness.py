"""SQL 难度分级（Spider 风格的轻量近似）.

按 gold SQL 的结构复杂度分到 easy/medium/hard/extra 四档，用于 EX 分桶统计，
定位「模型在复杂查询上掉点」的问题。基于 sqlglot 解析，规则为经验近似。
"""

from __future__ import annotations

import sqlglot
from sqlglot import exp

LEVELS = ["easy", "medium", "hard", "extra"]


def sql_hardness(sql: str, dialect: str = "sqlite") -> str:
    """返回难度档位。解析失败时按关键词兜底。"""
    try:
        tree = sqlglot.parse_one(sql, dialect=dialect)
    except Exception:  # noqa: BLE001
        return _keyword_fallback(sql)
    if tree is None:
        return _keyword_fallback(sql)

    # 集合操作 / 嵌套子查询 → extra
    if list(tree.find_all(exp.Union, exp.Intersect, exp.Except)):
        return "extra"
    subqueries = [s for s in tree.find_all(exp.Select)]
    if len(subqueries) > 1:  # 主 SELECT 之外还有子查询
        return "extra"

    joins = len(list(tree.find_all(exp.Join)))
    has_group = bool(list(tree.find_all(exp.Group)))
    has_having = bool(list(tree.find_all(exp.Having)))
    has_order = bool(list(tree.find_all(exp.Order)))
    has_agg = bool(list(tree.find_all(exp.AggFunc)))

    if joins >= 2 or (joins >= 1 and has_group and has_having):
        return "hard"
    if joins == 1 or has_group or has_having or (has_order and has_agg):
        return "medium"
    return "easy"


def _keyword_fallback(sql: str) -> str:
    s = sql.lower()
    if any(k in s for k in (" union ", " intersect ", " except ", "select", "(select")) and s.count("select") > 1:
        return "extra"
    if " join " in s and s.count(" join ") >= 2:
        return "hard"
    if " join " in s or " group by " in s:
        return "medium"
    return "easy"
