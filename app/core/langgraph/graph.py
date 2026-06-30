"""Text-to-SQL LangGraph 编排.

链路（融合手绘图① + text2sql 生产要素）：

  detect_language → rewrite → expand → retrieve ─┬─(无上下文)→ error → END
                                                 └→ schema_linking → generate_sql
       ↑(loop)                                                          ↓
  self_correct ←──(失败且未超次数)── validate_sql ──(通过)→ execute_sql ─(成功)→ format_answer → END
                                          │                    │
                                          └(超次数)→ format_answer ←(失败且超次数)┘

自纠错由 validate / execute 失败触发，回到 generate_sql 携带错误重生成，最多 SQL_MAX_RETRY 次。
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.core.config import settings
from app.core.langgraph import nodes
from app.core.langgraph.state import GraphState
from app.core.logging import logger


def _route_after_retrieve(state: GraphState) -> str:
    return "schema_linking" if state.get("schema_docs") else "error_node"


def _route_after_validate(state: GraphState) -> str:
    if not state.get("error"):
        return "execute_sql"
    return "self_correct" if state.get("attempt", 0) < settings.SQL_MAX_RETRY else "format_answer"


def _route_after_execute(state: GraphState) -> str:
    result = state.get("sql_result", {})
    if result.get("ok"):
        return "format_answer"
    return "self_correct" if state.get("attempt", 0) < settings.SQL_MAX_RETRY else "format_answer"

# 构建 text-to-SQL 图
def build_graph(checkpointer=None):
    """构建并编译 text-to-SQL 图。"""
    g = StateGraph(GraphState)

    g.add_node("detect_language", nodes.detect_language)
    g.add_node("rewrite", nodes.rewrite)
    g.add_node("expand", nodes.expand)
    g.add_node("retrieve", nodes.retrieve)
    g.add_node("schema_linking", nodes.schema_linking)
    g.add_node("generate_sql", nodes.generate_sql)
    g.add_node("validate_sql", nodes.validate_sql)
    g.add_node("execute_sql", nodes.execute_sql)
    g.add_node("self_correct", nodes.self_correct)
    g.add_node("format_answer", nodes.format_answer)
    g.add_node("error_node", nodes.error_node)

    g.add_edge(START, "detect_language")
    g.add_edge("detect_language", "rewrite")
    g.add_edge("rewrite", "expand")
    g.add_edge("expand", "retrieve")
    g.add_conditional_edges(
        "retrieve", _route_after_retrieve, {"schema_linking": "schema_linking", "error_node": "error_node"}
    )
    g.add_edge("schema_linking", "generate_sql")
    g.add_edge("generate_sql", "validate_sql")
    g.add_conditional_edges(
        "validate_sql",
        _route_after_validate,
        {"execute_sql": "execute_sql", "self_correct": "self_correct", "format_answer": "format_answer"},
    )
    g.add_conditional_edges(
        "execute_sql",
        _route_after_execute,
        {"format_answer": "format_answer", "self_correct": "self_correct"},
    )
    g.add_edge("self_correct", "generate_sql")
    g.add_edge("format_answer", END)
    g.add_edge("error_node", END)

    return g.compile(checkpointer=checkpointer)


# ---- 全局编译实例（应用启动时预热）----
_compiled = None


async def get_graph():
    """返回编译后的图（单例）。

    职责分离：
    - 多轮历史：由 chat_message 表提供（取最近若干轮），通过 state.history 传入，不依赖 checkpointer；
    - checkpointer：挂上 AsyncPostgresSaver，用于「特定场景」——人机交互 interrupt() 的断点续跑。
      因此每次 invoke 必须带 configurable.thread_id（会话用 session_id，单轮用临时 id）。
    挂载失败时降级为无检查点图（HIL 不可用，但主链路照常）。
    """
    global _compiled
    if _compiled is not None:
        return _compiled
    checkpointer = None
    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        from app.core.db import get_pool

        pool = await get_pool()
        checkpointer = AsyncPostgresSaver(pool)
        await checkpointer.setup()
        logger.info("checkpointer_ready", backend="postgres")
    except Exception as e:  # noqa: BLE001
        logger.warning("checkpointer_unavailable", error=str(e))
        checkpointer = None
    _compiled = build_graph(checkpointer=checkpointer)
    return _compiled
