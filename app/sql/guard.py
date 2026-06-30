"""SQL 安全护栏（text-to-SQL 的命门）.

用 sqlglot 解析并强制以下规则：
1. 仅允许单条 SELECT（拒绝多语句 / DDL / DML / 危险语句）；
2. 自动注入 LIMIT，防止全表扫描拖垮库；
3. 方言适配（sqlite / postgres）。

校验失败抛 SQLGuardError，由链路转入自纠错或报错。
"""

from __future__ import annotations

import sqlglot
from sqlglot import exp

from app.core.config import settings

# 明令禁止的语句类型（即便是只读连接也提前拦截）
_FORBIDDEN = (
    exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create, exp.Alter,
    exp.TruncateTable, exp.Command, exp.Grant,
)

_READ_ONLY_ROOTS = tuple(
    t
    for t in (
        exp.Select,
        exp.Union,
        getattr(exp, "Intersect", None),
        getattr(exp, "Except", None),
        exp.With,
    )
    if t is not None
)


class SQLGuardError(ValueError):
    """SQL 未通过安全校验。"""


def _strip_fences(sql: str) -> str:
    """去掉 LLM 可能输出的 ```sql ... ``` 围栏与多余空白。"""
    sql = sql.strip()
    if sql.startswith("```"):
        sql = sql.strip("`")
        if sql.lower().startswith("sql"):
            sql = sql[3:]
    return sql.strip().rstrip(";").strip()


def validate_and_secure(sql: str, dialect: str | None = None, max_rows: int | None = None) -> str:
    """校验并加固 SQL，返回可安全执行的最终 SQL。"""
    dialect = dialect or settings.SQL_DIALECT
    # 设置最大检索行数
    max_rows = max_rows or settings.SQL_MAX_ROWS
    # LLM 爱输出 ```sql ... ``` 和结尾分号，先剥掉；空的直接拒
    raw = _strip_fences(sql)
    if not raw:
        raise SQLGuardError("空 SQL")

    try:
        statements = sqlglot.parse(raw, dialect=dialect)
    except Exception as e:  # noqa: BLE001
        raise SQLGuardError(f"SQL 解析失败: {e}") from e

    statements = [s for s in statements if s is not None]
    if len(statements) != 1:
        raise SQLGuardError("只允许单条语句")

    stmt = statements[0]
    if isinstance(stmt, _FORBIDDEN) or stmt.find(*_FORBIDDEN):
        raise SQLGuardError(f"禁止的语句类型: {type(stmt).__name__}")
    # 顶层必须是 SELECT（或带 CTE 的 SELECT）
    if not isinstance(stmt, _READ_ONLY_ROOTS):
        raise SQLGuardError("仅允许 SELECT 查询")

    # 注入 LIMIT（若没有显式 limit）
    if not stmt.args.get("limit") and hasattr(stmt, "limit"):
        stmt = stmt.limit(max_rows)

    return stmt.sql(dialect=dialect)
