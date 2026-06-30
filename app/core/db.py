"""PostgreSQL 异步连接池（psycopg3）.

全应用共享一个 AsyncConnectionPool：
- RAG 向量 / 关键词检索
- schema 文档存取
- LangGraph 的 AsyncPostgresSaver 也复用该连接串
"""

from __future__ import annotations

from psycopg_pool import AsyncConnectionPool

from app.core.config import settings
from app.core.logging import logger

_pool: AsyncConnectionPool | None = None
_query_pool: AsyncConnectionPool | None = None


async def _configure_connection(conn) -> None:
    """初始化每条 PostgreSQL 连接的类型适配器。"""
    from pgvector.psycopg import register_vector_async

    await register_vector_async(conn)


async def get_pool() -> AsyncConnectionPool:
    """返回（惰性初始化的）全局连接池。"""
    global _pool
    if _pool is None:
        _pool = AsyncConnectionPool(
            conninfo=settings.postgres_dsn,
            min_size=settings.POSTGRES_POOL_MIN,
            max_size=settings.POSTGRES_POOL_MAX,
            open=False,
            kwargs={"autocommit": True},
            configure=_configure_connection,
        )
        await _pool.open(wait=True)
        logger.info("pg_pool_opened", min=settings.POSTGRES_POOL_MIN, max=settings.POSTGRES_POOL_MAX)
    return _pool


async def get_query_pool() -> AsyncConnectionPool:
    """返回业务查询库连接池。

    生产建议配置 QUERY_POSTGRES_* 为只读账号；应用元数据/RAG/checkpoint 继续走 get_pool()。
    """
    global _query_pool
    if _query_pool is None:
        _query_pool = AsyncConnectionPool(
            conninfo=settings.query_postgres_dsn,
            min_size=settings.QUERY_POSTGRES_POOL_MIN,
            max_size=settings.QUERY_POSTGRES_POOL_MAX,
            open=False,
            kwargs={"autocommit": False},
        )
        await _query_pool.open(wait=True)
        logger.info("query_pg_pool_opened", min=settings.QUERY_POSTGRES_POOL_MIN, max=settings.QUERY_POSTGRES_POOL_MAX)
    return _query_pool


async def close_pool() -> None:
    global _pool, _query_pool
    if _query_pool is not None:
        await _query_pool.close()
        _query_pool = None
        logger.info("query_pg_pool_closed")
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("pg_pool_closed")


async def health_check() -> bool:
    """数据库连通性检查（供 /health 使用）。"""
    try:
        pool = await get_pool()
        async with pool.connection() as conn, conn.cursor() as cur:
            await cur.execute("SELECT 1")
            await cur.fetchone()
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("db_health_check_failed", error=str(e))
        return False
