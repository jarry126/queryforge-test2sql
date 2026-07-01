"""节点：人工审核 SQL（Human-in-the-loop）。

该节点只在 HIL 测试/特定会话中启用。它通过 LangGraph interrupt()
暂停图执行，把 LLM 生成的 SQL 交给人审核；收到 Command(resume=...)
后再继续执行。
"""

from __future__ import annotations

from typing import Any

from langgraph.types import interrupt

from app.core.langgraph.state import GraphState


def _as_dict(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        return {"action": value}
    return {"action": "reject", "reason": f"不支持的人工审核输入类型: {type(value).__name__}"}


async def human_review_sql(state: GraphState) -> dict:
    """暂停等待人工审核 SQL。

    resume payload 支持：
    - {"action": "approve"}
    - {"action": "edit", "sql": "SELECT ..."}
    - {"action": "reject", "reason": "..."}
    """
    decision = interrupt(
        {
            "type": "sql_review",
            "question": state.get("rewritten_question") or state.get("question", ""),
            "db_id": state.get("db_id", ""),
            "sql": state.get("sql", ""),
            "attempt": state.get("attempt", 0),
            "instructions": "approve 通过；edit 修改 SQL；reject 拒绝本次执行。",
        }
    )
    data = _as_dict(decision)
    action = str(data.get("action", "approve")).lower().strip()

    if action == "approve":
        return {"error": None}

    if action == "edit":
        sql = str(data.get("sql", "")).strip()
        if not sql:
            return {"error": "人工审核失败: edit 操作必须提供 sql"}
        return {"sql": sql, "error": None}

    if action == "reject":
        reason = str(data.get("reason") or "人工拒绝执行 SQL").strip()
        return {
            "success": False,
            "error": f"人工拒绝: {reason}",
            "sql_result": {"ok": False, "columns": [], "rows": [], "row_count": 0, "error": reason},
        }

    return {"error": f"人工审核失败: 未知 action={action}"}
