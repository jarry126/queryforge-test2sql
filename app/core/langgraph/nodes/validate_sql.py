"""节点：SQL 安全校验与加固（sqlglot guard）。"""

from __future__ import annotations

from app.core.config import settings
from app.core.langgraph.state import GraphState
from app.core.logging import logger
from app.sql.guard import SQLGuardError, validate_and_secure


async def validate_sql(state: GraphState) -> dict:
    sql = state.get("sql", "")
    try:
        secured = validate_and_secure(sql, dialect=settings.SQL_DIALECT)
    except SQLGuardError as e:
        logger.warning("validate_sql_rejected", sql=sql, error=str(e), attempt=state.get("attempt", 0))
        return {"error": f"SQL 校验未通过: {e}"}
    logger.info("validate_sql_ok", sql=secured)
    return {"sql": secured, "error": None}
