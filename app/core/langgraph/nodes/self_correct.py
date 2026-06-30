"""节点：自纠错（对应链路环路）。

仅负责递增尝试计数；具体修正在 generate_sql 中读取 error + 上次 sql 完成。
"""

from __future__ import annotations

from app.core.langgraph.state import GraphState
from app.core.logging import logger
from app.core.metrics import sql_self_correct_total


async def self_correct(state: GraphState) -> dict:
    attempt = state.get("attempt", 0) + 1
    sql_self_correct_total.inc()
    logger.info("self_correct", attempt=attempt, error=state.get("error"))
    return {"attempt": attempt}
