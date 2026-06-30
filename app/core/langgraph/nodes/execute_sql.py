"""节点：沙箱执行 SQL。"""

from __future__ import annotations

from app.core.langgraph.state import GraphState
from app.core.logging import logger
from app.sql.executor import execute


async def execute_sql(state: GraphState) -> dict:
    db_id = state.get("db_id", "")
    sql = state.get("sql", "")
    result = await execute(db_id, sql)
    payload = {
        "ok": result.ok,
        "columns": result.columns,
        "rows": result.rows,
        "error": result.error,
        "row_count": result.row_count,
    }
    if result.ok:
        logger.info("execute_sql_ok", db_id=db_id, sql=sql, row_count=result.row_count, columns=result.columns)
    else:
        logger.warning("execute_sql_error", db_id=db_id, sql=sql, error=result.error, attempt=state.get("attempt", 0))
    return {"sql_result": payload, "error": None if result.ok else result.error}
