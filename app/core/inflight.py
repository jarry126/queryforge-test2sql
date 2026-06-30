"""在途请求并发控制。

slowapi 控制进入速率；这里控制当前正在执行的重链路请求数量。
超过并发上限时快速失败，避免请求在应用内无限排队。
"""

from __future__ import annotations

import asyncio
import time
import uuid
from contextlib import asynccontextmanager

from app.core.cache import get_redis
from app.core.config import settings
from app.core.errors import AppError
from app.core.logging import logger

_query_sem: asyncio.Semaphore | None = None
_REDIS_KEY = "qf:inflight:query"
_ACQUIRE_SCRIPT = """
redis.call('ZREMRANGEBYSCORE', KEYS[1], 0, ARGV[1])
local count = redis.call('ZCARD', KEYS[1])
if count >= tonumber(ARGV[2]) then
  return 0
end
redis.call('ZADD', KEYS[1], ARGV[3], ARGV[4])
redis.call('EXPIRE', KEYS[1], ARGV[5])
return 1
"""


def _query_semaphore() -> asyncio.Semaphore:
    global _query_sem
    if _query_sem is None:
        _query_sem = asyncio.Semaphore(settings.QUERY_MAX_INFLIGHT)
    return _query_sem


@asynccontextmanager
async def query_inflight_slot():
    """获取一个 /query 在途并发槽；没有空位时直接返回 503。"""
    if settings.QUERY_INFLIGHT_BACKEND == "redis":
        async with _redis_query_slot():
            yield
        return
    async with _local_query_slot():
        yield


@asynccontextmanager
async def _local_query_slot():
    """单进程在途并发槽，用于本地开发或 Redis 不可用时的开发回退。"""
    sem = _query_semaphore()
    if sem.locked():
        raise AppError(503, "query_overloaded", "当前查询请求过多，请稍后重试") from None
    await sem.acquire()
    try:
        yield
    finally:
        sem.release()


@asynccontextmanager
async def _redis_query_slot():
    """Redis 分布式在途并发槽。

    用 sorted set 存放 token -> expires_at。获取前清理过期 token，释放时删除自己的 token。
    """
    redis = await get_redis()
    if redis is None:
        if settings.is_production:
            raise AppError(503, "inflight_backend_unavailable", "服务繁忙，请稍后重试")
        logger.warning("query_inflight_redis_unavailable_fallback_local")
        async with _local_query_slot():
            yield
        return

    token = uuid.uuid4().hex
    acquired = False
    now = time.time()
    expires_at = now + settings.QUERY_INFLIGHT_TTL_SECONDS
    try:
        ok = await redis.eval(
            _ACQUIRE_SCRIPT,
            1,
            _REDIS_KEY,
            now,
            settings.QUERY_MAX_INFLIGHT,
            expires_at,
            token,
            settings.QUERY_INFLIGHT_TTL_SECONDS,
        )
        if int(ok) != 1:
            raise AppError(503, "query_overloaded", "当前查询请求过多，请稍后重试")
        acquired = True
        yield
    finally:
        if acquired:
            try:
                await redis.zrem(_REDIS_KEY, token)
            except Exception as exc:  # noqa: BLE001
                logger.warning("query_inflight_release_failed", error=str(exc))
