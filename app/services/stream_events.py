"""面向用户的流式进度事件。

这里只暴露经过整理的执行阶段，不暴露模型原始思维链、Prompt、检索全文或内部异常。
节点到用户文案的映射集中在这个深模块中，API 和前端不需要理解 LangGraph 内部结构。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class QueryStreamEvent:
    """一次流式事件；name 对应 SSE event，data 必须可 JSON 序列化。"""

    name: str
    data: dict[str, Any]


def progress(stage: str, status: str, message: str, **details: Any) -> QueryStreamEvent:
    data: dict[str, Any] = {"stage": stage, "status": status, "message": message}
    if details:
        data["details"] = details
    return QueryStreamEvent("progress", data)


def plan_event() -> QueryStreamEvent:
    return QueryStreamEvent(
        "plan",
        {
            "steps": [
                {"stage": "understand", "label": "理解问题"},
                {"stage": "retrieve", "label": "查找相关表结构"},
                {"stage": "generate_sql", "label": "生成并校验 SQL"},
                {"stage": "execute_sql", "label": "执行只读查询"},
                {"stage": "format_answer", "label": "整理答案"},
            ]
        },
    )


def events_after_node(node: str, update: dict[str, Any], max_retries: int) -> list[QueryStreamEvent]:
    """把真实 LangGraph 节点更新转换成安全、稳定的用户进度事件。"""

    if node == "detect_language":
        return [
            progress("understand", "completed", "已识别问题语言"),
            progress("rewrite", "running", "正在结合会话上下文理解问题"),
        ]
    if node == "rewrite":
        return [
            progress("rewrite", "completed", "问题上下文已整理"),
            progress("expand", "running", "正在生成更适合检索的表达"),
        ]
    if node == "expand":
        return [
            progress("expand", "completed", "检索表达已准备"),
            progress("retrieve", "running", "正在查找相关表结构和示例"),
        ]
    if node == "retrieve":
        schema_docs = update.get("schema_docs") or []
        fewshots = update.get("fewshots") or []
        if not schema_docs:
            return [progress("retrieve", "failed", "没有找到足够的相关表结构")]
        return [
            progress(
                "retrieve",
                "completed",
                "已找到相关表结构和查询示例",
                schema_documents=len(schema_docs),
                examples=len(fewshots),
            ),
            progress("schema_linking", "running", "正在整理问题涉及的表和字段"),
        ]
    if node == "schema_linking":
        return [
            progress("schema_linking", "completed", "相关表和字段已确定"),
            progress("generate_sql", "running", "正在生成查询语句"),
        ]
    if node == "generate_sql":
        return [
            progress("generate_sql", "completed", "查询语句已生成"),
            progress("validate_sql", "running", "正在进行 SQL 安全校验"),
        ]
    if node == "human_review_sql":
        if update.get("error"):
            return [progress("human_review_sql", "failed", "SQL 人工审核未通过")]
        return [progress("human_review_sql", "completed", "SQL 人工审核已通过")]
    if node == "validate_sql":
        if update.get("error"):
            return [progress("validate_sql", "retrying", "SQL 校验未通过，准备自动修正")]
        return [
            progress("validate_sql", "completed", "SQL 安全校验通过"),
            progress("execute_sql", "running", "正在执行只读查询"),
        ]
    if node == "execute_sql":
        result = update.get("sql_result") or {}
        if result.get("ok"):
            return [
                progress(
                    "execute_sql",
                    "completed",
                    f"查询执行完成，共获得 {result.get('row_count', 0)} 行结果",
                    row_count=result.get("row_count", 0),
                ),
                progress("format_answer", "running", "正在根据查询结果整理答案"),
            ]
        return [progress("execute_sql", "retrying", "查询执行未成功，准备自动修正")]
    if node == "self_correct":
        attempt = int(update.get("attempt", 0))
        return [
            progress(
                "self_correct",
                "retrying",
                f"正在修正查询语句（第 {attempt + 1} 次生成）",
                attempt=attempt,
                max_retries=max_retries,
            ),
            progress("generate_sql", "running", "正在重新生成查询语句"),
        ]
    if node == "format_answer":
        return [progress("format_answer", "completed", "答案整理完成")]
    if node == "error_node":
        return [progress("retrieve", "failed", "未找到足够的表结构信息")]
    return []


def encode_sse(event: QueryStreamEvent, event_id: int) -> str:
    """编码单个 SSE 帧。data 固定为单行 JSON，避免换行破坏协议。"""

    payload = {
        **event.data,
        "sequence": event_id,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    return (
        f"id: {event_id}\n"
        f"event: {event.name}\n"
        f"data: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n"
    )
