"""LangGraph 状态定义.

text-to-SQL 链路在节点间流转的全部上下文。
"""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langgraph.graph.message import add_messages


class GraphState(TypedDict, total=False):
    """链路状态。total=False 允许节点只返回增量字段。"""

    # 输入
    messages: Annotated[list, add_messages]  # 供 HIL/工具调用的图内消息（不承载跨轮历史）
    history: list[dict]  # 多轮上下文：来自 chat_message 的最近若干轮 {role, content}（普通覆盖字段）
    question: str
    db_id: str

    # 预处理
    language: str  # zh | en | de | ...
    rewritten_question: str
    expanded_queries: list[str]

    # 检索
    schema_docs: list[dict]
    fewshots: list[dict]
    doc_context: list[dict]  # 业务文档块（图②上传链路检索结果）
    linked_schema: str  # 喂给 LLM 的紧凑 schema/DDL

    # 生成与执行
    sql: str
    sql_result: dict[str, Any]  # {ok, columns, rows, error, row_count}
    error: str | None
    attempt: int

    # 输出
    answer: str
    success: bool
    from_cache: bool
