"""消息反馈存储（raw SQL via 连接池）。"""

from __future__ import annotations

from app.core.db import get_pool


def _row_to_feedback(row: tuple) -> dict:
    return {
        "id": row[0],
        "message_id": row[1],
        "session_id": row[2],
        "rating": row[3],
        "comment": row[4],
        "question_text": row[5] or "",
        "created_at": row[6].isoformat() if row[6] else None,
        "updated_at": row[7].isoformat() if row[7] else None,
    }


_FEEDBACK_COLS = """
    id, message_id, session_id, rating, comment, question_text, created_at, updated_at
"""


async def get_message_for_user(session_id: str, message_id: int, user_id: int) -> dict | None:
    """返回助手消息及同轮用户问题；校验会话归属。"""
    pool = await get_pool()
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            """
            SELECT m.id, m.role, m.content, m.turn_id, m.session_id
            FROM chat_message m
            JOIN chat_session s ON s.id = m.session_id
            WHERE m.id = %s AND m.session_id = %s AND s.user_id = %s
            """,
            (message_id, session_id, user_id),
        )
        row = await cur.fetchone()
        if not row:
            return None
        if row[1] != "assistant":
            return None

        question_text = ""
        turn_id = row[3]
        if turn_id:
            await cur.execute(
                """
                SELECT content FROM chat_message
                WHERE session_id = %s AND turn_id = %s AND role = 'user'
                ORDER BY id LIMIT 1
                """,
                (session_id, turn_id),
            )
            q = await cur.fetchone()
            question_text = q[0] if q else ""
        else:
            await cur.execute(
                """
                SELECT content FROM chat_message
                WHERE session_id = %s AND role = 'user' AND id < %s
                ORDER BY id DESC LIMIT 1
                """,
                (session_id, message_id),
            )
            q = await cur.fetchone()
            question_text = q[0] if q else ""

        return {
            "id": row[0],
            "role": row[1],
            "content": row[2],
            "turn_id": turn_id,
            "session_id": row[4],
            "question_text": question_text,
        }


async def upsert_feedback(
    *,
    message_id: int,
    user_id: int,
    session_id: str,
    rating: str,
    comment: str | None,
    question_text: str,
) -> dict:
    pool = await get_pool()
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            f"""
            INSERT INTO message_feedback
                (message_id, user_id, session_id, rating, comment, question_text)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (message_id, user_id) DO UPDATE SET
                rating = EXCLUDED.rating,
                comment = EXCLUDED.comment,
                question_text = EXCLUDED.question_text,
                updated_at = now()
            RETURNING {_FEEDBACK_COLS}
            """,
            (message_id, user_id, session_id, rating, comment, question_text),
        )
        row = await cur.fetchone()
        assert row is not None
        return _row_to_feedback(row)


async def get_feedback(message_id: int, user_id: int) -> dict | None:
    pool = await get_pool()
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            f"""
            SELECT {_FEEDBACK_COLS}
            FROM message_feedback
            WHERE message_id = %s AND user_id = %s
            """,
            (message_id, user_id),
        )
        row = await cur.fetchone()
        return _row_to_feedback(row) if row else None


async def list_feedback_for_user(
    user_id: int,
    *,
    rating: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    pool = await get_pool()
    async with pool.connection() as conn, conn.cursor() as cur:
        if rating:
            await cur.execute(
                f"""
                SELECT {_FEEDBACK_COLS}
                FROM message_feedback
                WHERE user_id = %s AND rating = %s
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                (user_id, rating, limit, offset),
            )
        else:
            await cur.execute(
                f"""
                SELECT {_FEEDBACK_COLS}
                FROM message_feedback
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                (user_id, limit, offset),
            )
        return [_row_to_feedback(r) for r in await cur.fetchall()]


async def map_feedback_by_message_ids(user_id: int, message_ids: list[int]) -> dict[int, dict]:
    if not message_ids:
        return {}
    pool = await get_pool()
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            f"""
            SELECT {_FEEDBACK_COLS}
            FROM message_feedback
            WHERE user_id = %s AND message_id = ANY(%s)
            """,
            (user_id, message_ids),
        )
        return {row[1]: _row_to_feedback(row) for row in await cur.fetchall()}
