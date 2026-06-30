"""SQL 沙箱执行.

只读执行已通过 guard 的 SQL，支持两类目标：
- sqlite：CSpider 的 database/<db_id>/<db_id>.sqlite（评测与 MVP 默认）；
- postgres：生产业务库，使用只读连接 + statement_timeout。

统一限制：执行超时 + 行数上限。返回列名 + 行 + 错误。
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
from dataclasses import dataclass, field

from app.core.config import settings
from app.core.metrics import sql_exec_total


@dataclass
class ExecResult:
    ok: bool
    columns: list[str] = field(default_factory=list)
    rows: list[list] = field(default_factory=list)
    error: str | None = None
    row_count: int = 0


def _sqlite_path(db_id: str) -> str:
    base = settings.CSPIDER_DB_DIR
    # CSpider 目录结构：<dir>/<db_id>/<db_id>.sqlite
    candidate = os.path.join(base, db_id, f"{db_id}.sqlite")
    if os.path.exists(candidate):
        return candidate
    # 兜底：直接 <dir>/<db_id>.sqlite
    alt = os.path.join(base, f"{db_id}.sqlite")
    return alt


def _run_sqlite(db_id: str, sql: str, max_rows: int) -> ExecResult:
    path = _sqlite_path(db_id)
    if not os.path.exists(path):
        return ExecResult(ok=False, error=f"找不到数据库文件: {path}")
    # 只读打开
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        conn.row_factory = None
        cur = conn.cursor()
        cur.execute(sql)
        cols = [c[0] for c in cur.description] if cur.description else []
        rows = cur.fetchmany(max_rows)
        return ExecResult(ok=True, columns=cols, rows=[list(r) for r in rows], row_count=len(rows))
    except Exception as e:  # noqa: BLE001
        return ExecResult(ok=False, error=str(e))
    finally:
        conn.close()


async def execute(db_id: str, sql: str, dialect: str | None = None) -> ExecResult:
    """异步执行（sqlite 在线程池中跑，避免阻塞事件循环）。"""
    dialect = dialect or settings.SQL_DIALECT
    max_rows = settings.SQL_MAX_ROWS
    timeout = settings.SQL_EXEC_TIMEOUT_SECONDS
    try:
        if dialect == "sqlite":
            result = await asyncio.wait_for(
                asyncio.to_thread(_run_sqlite, db_id, sql, max_rows), timeout=timeout
            )
        else:
            result = await _run_postgres(sql, max_rows, timeout)
    except TimeoutError:
        result = ExecResult(ok=False, error=f"执行超时（>{timeout}s）")
    sql_exec_total.labels(status="ok" if result.ok else "error").inc()
    return result


async def _run_postgres(sql: str, max_rows: int, timeout: int) -> ExecResult:
    """对业务 postgres 只读执行（独立查询连接池 + 只读事务 + statement_timeout）。"""
    from app.core.db import get_query_pool

    pool = await get_query_pool()
    async with pool.connection() as conn:
        try:
            async with conn.transaction():
                async with conn.cursor() as cur:
                    await cur.execute("SET TRANSACTION READ ONLY")
                    await cur.execute(f"SET LOCAL statement_timeout = {timeout * 1000}")
                    await cur.execute(sql)
                    cols = [c.name for c in cur.description] if cur.description else []
                    rows = await cur.fetchmany(max_rows)
                    return ExecResult(ok=True, columns=cols, rows=[list(r) for r in rows], row_count=len(rows))
        except Exception as e:  # noqa: BLE001
            return ExecResult(ok=False, error=str(e))
