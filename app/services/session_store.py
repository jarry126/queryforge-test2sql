"""会话与消息存储（raw SQL via 连接池）.

chat_session 是用户可见的对话；其 id 同时作为 LangGraph 的 thread_id。
chat_message 是 UI 展示与多轮历史的真实来源。
"""

from __future__ import annotations

import json
import uuid

from app.core.db import get_pool


async def create_session(user_id: int, db_id: str, title: str = "新会话") -> dict:
    sid = uuid.uuid4().hex
    pool = await get_pool()
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "INSERT INTO chat_session (id, user_id, db_id, title) VALUES (%s, %s, %s, %s)",
            (sid, user_id, db_id, title),
        )
    return {"id": sid, "db_id": db_id, "title": title}


async def list_sessions(user_id: int) -> list[dict]:
    pool = await get_pool()
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            """
            SELECT id, title, db_id, updated_at
            FROM chat_session WHERE user_id = %s ORDER BY updated_at DESC
            """,
            (user_id,),
        )
        return [
            {"id": r[0], "title": r[1], "db_id": r[2], "updated_at": r[3].isoformat() if r[3] else None}
            for r in await cur.fetchall()
        ]


async def get_session(session_id: str, user_id: int) -> dict | None:
    pool = await get_pool()
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "SELECT id, title, db_id FROM chat_session WHERE id = %s AND user_id = %s",
            (session_id, user_id),
        )
        row = await cur.fetchone()
        return {"id": row[0], "title": row[1], "db_id": row[2]} if row else None


async def delete_session(session_id: str, user_id: int) -> None:
    pool = await get_pool()
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "DELETE FROM chat_session WHERE id = %s AND user_id = %s", (session_id, user_id)
        )


async def rename_if_default(session_id: str, title: str) -> None:
    """会话标题仍是默认值时，用首条问题改名。"""
    pool = await get_pool()
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "UPDATE chat_session SET title = %s WHERE id = %s AND title = '新会话'",
            (title, session_id),
        )


async def list_messages(session_id: str) -> list[dict]:
    pool = await get_pool()
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            """
            SELECT role, content, sql, result, turn_id FROM chat_message
            WHERE session_id = %s ORDER BY id
            """,
            (session_id,),
        )
        return [
            {"role": r[0], "content": r[1], "sql": r[2], "result": r[3], "turn_id": r[4]}
            for r in await cur.fetchall()
        ]


async def add_message(
    session_id: str,
    role: str,
    content: str,
    sql: str | None = None,
    result: dict | None = None,
    turn_id: str | None = None,
) -> None:
    pool = await get_pool()
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO chat_message (session_id, role, content, sql, result, turn_id)
            VALUES (%s, %s, %s, %s, %s::jsonb, %s)
            """,
            (session_id, role, content, sql, json.dumps(result, ensure_ascii=False) if result else None, turn_id),
        )
        await cur.execute("UPDATE chat_session SET updated_at = now() WHERE id = %s", (session_id,))


async def add_turn(
    session_id: str,
    question: str,
    answer: str,
    sql: str | None,
    result: dict | None,
    turn_id: str,
) -> None:
    """事务化写入一轮问答，避免只写入 user 或 assistant 的半轮状态。"""
    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO chat_message (session_id, role, content, turn_id)
                    VALUES (%s, 'user', %s, %s)
                    """,
                    (session_id, question, turn_id),
                )
                await cur.execute(
                    """
                    INSERT INTO chat_message (session_id, role, content, sql, result, turn_id)
                    VALUES (%s, 'assistant', %s, %s, %s::jsonb, %s)
                    """,
                    (
                        session_id,
                        answer,
                        sql,
                        json.dumps(result, ensure_ascii=False) if result else None,
                        turn_id,
                    ),
                )
                await cur.execute("UPDATE chat_session SET updated_at = now() WHERE id = %s", (session_id,))


async def list_databases() -> list[str]:
    """已灌库的 db_id 列表（供前端新建会话时选择目标库）。"""
    pool = await get_pool()
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute("SELECT DISTINCT db_id FROM schema_doc ORDER BY db_id")
        return [r[0] for r in await cur.fetchall()]
