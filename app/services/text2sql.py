"""Text-to-SQL 编排服务.

串起：语义缓存 → LangGraph 链路 → 写缓存 → 组装响应。
是 API 层与 LangGraph 之间的薄封装，便于复用（API / 评测 / 冒烟脚本共用）。
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncGenerator
from typing import Any, cast

from langchain_core.runnables import RunnableConfig

from app.core.cache import get_cached, set_cached
from app.core.config import settings
from app.core.errors import classify
from app.core.langgraph.graph import get_graph
from app.core.langgraph.state import GraphState
from app.core.logging import logger
from app.core.metrics import query_latency_seconds, query_requests_total
from app.core.observability import get_langfuse_handler
from app.core.semantic_cache import get_semantic_cached, set_semantic_cached
from app.schemas.query import QueryRequest, QueryResponse
from app.services.stream_events import QueryStreamEvent, events_after_node, plan_event, progress


def _history_to_dicts(history) -> list[dict]:
    """把请求里的历史统一成 [{role, content}]（供 state.history 用于多轮改写）。"""
    out = []
    for turn in history:
        role = turn.role if hasattr(turn, "role") else turn.get("role")
        content = turn.content if hasattr(turn, "content") else turn.get("content")
        out.append({"role": role, "content": content})
    return out


async def run_query(req: QueryRequest) -> QueryResponse:
    """执行一次 text-to-SQL 查询。"""
    start = time.perf_counter()

    # 缓存仅用于「无历史上下文」的请求。带历史的多轮请求答案依赖对话上下文，
    # 不能只按 (db_id, question) 做键，否则会命中错误结果——故有历史就跳过缓存。
    # 注意：thread_id 现在每次都会有（checkpointer 需要），故缓存判断只看 history。
    use_cache = not req.history

    if use_cache:
        # 1) 精确缓存（Redis，命中即跳过整条链路）
        cached = await get_cached(req.db_id, req.question)
        if cached:
            query_requests_total.labels(status="cache_hit").inc()
            return QueryResponse(**cached, from_cache=True)

        # 1b) 语义近似缓存（pgvector，命中同义问题；默认关闭，见 SEMANTIC_CACHE_ENABLED）
        sem = await get_semantic_cached(req.db_id, req.question)
        if sem:
            query_requests_total.labels(status="semantic_cache_hit").inc()
            await set_cached(req.db_id, req.question, sem)  # 回填精确缓存
            return QueryResponse(**sem, from_cache=True)

    # 2) 调用 LangGraph
    graph = await get_graph()
    init_state: GraphState = {
        "question": req.question,
        "db_id": req.db_id,
        "attempt": 0,
        "history": _history_to_dicts(req.history),  # 多轮上下文（来自 chat_message）
    }
    # checkpointer 需要 thread_id：会话用 session_id，单轮查询用一次性临时 id
    thread_id = req.thread_id or f"oneshot-{uuid.uuid4().hex}"
    config: RunnableConfig = {
        "recursion_limit": 25,
        "configurable": {"thread_id": thread_id},
    }
    if handler := get_langfuse_handler():
        config["callbacks"] = [handler]

    try:
        final = await graph.ainvoke(init_state, config=config)
    except Exception as e:  # noqa: BLE001
        # 图本身抛异常（上游限流/超时/熔断/未知 bug）→ 分类后抛出，由 HTTP 全局处理器
        # 映射到 429/503/500 + 友好文案；完整堆栈进日志。注意这与"图正常返回但 success=false"
        # （SQL 多次自纠错仍失败）不同——后者会正常返回 QueryResponse。
        err = classify(e)
        logger.exception("graph_invoke_failed", category=err.category)
        query_requests_total.labels(status="error").inc()
        query_latency_seconds.labels(status="error").observe(time.perf_counter() - start)
        raise err from e

    result = final.get("sql_result", {}) or {}
    resp = QueryResponse(
        question=req.question,
        db_id=req.db_id,
        sql=final.get("sql", ""),
        success=bool(final.get("success")),
        answer=final.get("answer", ""),
        language=final.get("language", "zh"),
        columns=result.get("columns", []),
        rows=result.get("rows", []),
        row_count=result.get("row_count", 0),
        attempts=final.get("attempt", 0),
        error=final.get("error"),
    )

    status = "ok" if resp.success else "failed"
    query_requests_total.labels(status=status).inc()
    query_latency_seconds.labels(status=status).observe(time.perf_counter() - start)

    # 3) 写缓存（仅成功结果、且为单轮查询）：精确 + 语义
    if resp.success and use_cache:
        payload = resp.model_dump(exclude={"from_cache"})
        await set_cached(req.db_id, req.question, payload)
        await set_semantic_cached(req.db_id, req.question, payload)
    return resp


async def run_query_stream(req: QueryRequest) -> AsyncGenerator[QueryStreamEvent]:
    """执行查询并输出真实 LangGraph 节点进度，最后输出完整 result 事件。

    第一版只流式输出安全进度，最终自然语言答案仍作为完整结果返回。这样不改变
    现有节点的重试、熔断、缓存和持久化语义；逐 Token 答案可在后续迭代增加。
    """

    start = time.perf_counter()
    yield QueryStreamEvent(
        "meta",
        {"thread_id": req.thread_id, "db_id": req.db_id, "stream_version": 1},
    )
    yield plan_event()
    yield progress("accepted", "completed", "已收到问题")

    use_cache = not req.history
    if use_cache:
        yield progress("cache", "running", "正在检查可复用的历史结果")
        cached = await get_cached(req.db_id, req.question)
        if cached:
            query_requests_total.labels(status="cache_hit").inc()
            resp = QueryResponse(**cached, from_cache=True)
            yield progress("cache", "completed", "已找到可复用结果")
            yield QueryStreamEvent("result", resp.model_dump(mode="json"))
            return

        sem = await get_semantic_cached(req.db_id, req.question)
        if sem:
            query_requests_total.labels(status="semantic_cache_hit").inc()
            await set_cached(req.db_id, req.question, sem)
            resp = QueryResponse(**sem, from_cache=True)
            yield progress("cache", "completed", "已找到语义相近的历史结果")
            yield QueryStreamEvent("result", resp.model_dump(mode="json"))
            return
        yield progress("cache", "completed", "未命中缓存，将执行完整分析")

    graph = await get_graph()
    init_state: GraphState = {
        "question": req.question,
        "db_id": req.db_id,
        "attempt": 0,
        "history": _history_to_dicts(req.history),
    }
    thread_id = req.thread_id or f"oneshot-{uuid.uuid4().hex}"
    config: RunnableConfig = {
        "recursion_limit": 25,
        "configurable": {"thread_id": thread_id},
    }
    if handler := get_langfuse_handler():
        config["callbacks"] = [handler]

    yield progress("understand", "running", "正在理解问题并识别语言")
    final: GraphState | None = None
    try:
        async for stream_item in graph.astream(
            init_state,
            config=config,
            stream_mode=["updates", "values"],
        ):
            mode, chunk = cast(tuple[str, Any], stream_item)
            if mode == "values":
                final = cast(GraphState, chunk)
                continue
            if mode != "updates" or not isinstance(chunk, dict):
                continue
            for node, update in cast(dict[str, Any], chunk).items():
                if not isinstance(update, dict):
                    continue
                for event in events_after_node(node, update, settings.SQL_MAX_RETRY):
                    yield event
    except Exception as e:  # noqa: BLE001
        err = classify(e)
        logger.exception("graph_stream_failed", category=err.category)
        query_requests_total.labels(status="error").inc()
        query_latency_seconds.labels(status="error").observe(time.perf_counter() - start)
        raise err from e

    if final is None:
        raise RuntimeError("LangGraph stream ended without a final state")

    result = final.get("sql_result", {}) or {}
    resp = QueryResponse(
        question=req.question,
        db_id=req.db_id,
        sql=final.get("sql", ""),
        success=bool(final.get("success")),
        answer=final.get("answer", ""),
        language=final.get("language", "zh"),
        columns=result.get("columns", []),
        rows=result.get("rows", []),
        row_count=result.get("row_count", 0),
        attempts=final.get("attempt", 0),
        error=final.get("error"),
    )

    status = "ok" if resp.success else "failed"
    query_requests_total.labels(status=status).inc()
    query_latency_seconds.labels(status=status).observe(time.perf_counter() - start)

    if resp.success and use_cache:
        payload = resp.model_dump(exclude={"from_cache"})
        await set_cached(req.db_id, req.question, payload)
        await set_semantic_cached(req.db_id, req.question, payload)

    yield QueryStreamEvent("result", resp.model_dump(mode="json"))
