"""会话接口：建/列/取消息/删 + 多轮对话查询。

多轮：每次 chat 从 chat_message 表读取本会话历史作为上下文传入链路（DB 是历史的唯一真相来源），
因此带历史的请求会自动跳过缓存（见 services/text2sql）。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.inflight import query_inflight_slot
from app.core.limiter import limiter
from app.schemas.auth import ChatMessage, ChatRequest, CreateSessionRequest, SessionInfo
from app.schemas.query import QueryRequest, QueryResponse
from app.services import session_store
from app.services.text2sql import run_query

router = APIRouter(tags=["sessions"])


@router.get("/databases", response_model=list[str])
async def databases(user: dict = Depends(get_current_user)) -> list[str]:
    """可选目标数据库（已灌库的 db_id）。"""
    return await session_store.list_databases()


@router.post("/sessions", response_model=SessionInfo)
async def create_session(body: CreateSessionRequest, user: dict = Depends(get_current_user)) -> SessionInfo:
    s = await session_store.create_session(user["id"], body.db_id, body.title)
    return SessionInfo(**s)


@router.get("/sessions", response_model=list[SessionInfo])
async def list_sessions(user: dict = Depends(get_current_user)) -> list[SessionInfo]:
    return [SessionInfo(**s) for s in await session_store.list_sessions(user["id"])]


@router.get("/sessions/{session_id}/messages", response_model=list[ChatMessage])
async def get_messages(session_id: str, user: dict = Depends(get_current_user)) -> list[ChatMessage]:
    if not await session_store.get_session(session_id, user["id"]):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    return [ChatMessage(**m) for m in await session_store.list_messages(session_id)]


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, user: dict = Depends(get_current_user)) -> dict:
    await session_store.delete_session(session_id, user["id"])
    return {"ok": True}


@router.post("/sessions/{session_id}/chat", response_model=QueryResponse)
@limiter.shared_limit(settings.RATE_LIMIT_QUERY_GLOBAL, scope="query-global")
@limiter.limit(settings.RATE_LIMIT_QUERY)
async def chat(
    request: Request, session_id: str, body: ChatRequest, user: dict = Depends(get_current_user)
) -> QueryResponse:
    """在会话内多轮提问：带历史调用链路，并把本轮问答持久化。"""
    session = await session_store.get_session(session_id, user["id"])
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="问题不能为空")

    # 取本会话最近 HISTORY_TURNS 轮问答作为多轮上下文（来自 chat_message，非 checkpointer）
    history = await session_store.list_messages(session_id)
    recent = history[-settings.HISTORY_TURNS * 2 :]
    req = QueryRequest(
        question=question,
        db_id=session["db_id"],
        thread_id=session_id,  # 会话 id 作为 checkpointer thread_id（HIL/断点续跑用）
        history=[{"role": m["role"], "content": m["content"]} for m in recent],
    )
    async with query_inflight_slot():
        resp = await run_query(req)

    # 持久化：用户消息 + 助手消息（含 SQL 与结果）
    turn_id = uuid.uuid4().hex
    await session_store.add_turn(
        session_id,
        question,
        resp.answer,
        resp.sql,
        result={"columns": resp.columns, "rows": resp.rows, "row_count": resp.row_count},
        turn_id=turn_id,
    )
    # 首轮自动用问题作为会话标题
    if not history:
        await session_store.rename_if_default(session_id, question[:30])
    return resp
