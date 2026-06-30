"""用户存储（raw SQL via 连接池）。"""

from __future__ import annotations

from app.core.db import get_pool


async def create_user(username: str, password_hash: str) -> dict:
    pool = await get_pool()
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "INSERT INTO app_user (username, password_hash) VALUES (%s, %s) RETURNING id, username",
            (username, password_hash),
        )
        row = await cur.fetchone()
        return {"id": row[0], "username": row[1]}


async def get_user_by_username(username: str) -> dict | None:
    pool = await get_pool()
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "SELECT id, username, password_hash FROM app_user WHERE username = %s", (username,)
        )
        row = await cur.fetchone()
        if not row:
            return None
        return {"id": row[0], "username": row[1], "password_hash": row[2]}


async def get_user_by_id(user_id: int) -> dict | None:
    pool = await get_pool()
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute("SELECT id, username FROM app_user WHERE id = %s", (user_id,))
        row = await cur.fetchone()
        return {"id": row[0], "username": row[1]} if row else None
