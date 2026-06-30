"""Redis 语义缓存.

text-to-SQL 的关键提速手段：把 (db_id, 规范化问题) -> {sql, rows} 缓存。
- MVP 采用「精确归一化键」（小写 + 去空白 + 去标点），命中即跳过整条 LLM 链路。
- 向量近似缓存（相似问命中）列为 Phase 3 增强。
未启用 / 连接失败时全部降级为 miss，不影响主链路。
"""

from __future__ import annotations

import hashlib
import json
import re

from app.core.config import settings
from app.core.logging import logger
from app.core.metrics import cache_total

_redis = None


async def get_redis():
    """返回 redis 异步客户端（单例）；未启用返回 None。"""
    global _redis
    if not settings.REDIS_ENABLED:
        return None
    if _redis is not None:
        return _redis
    try:
        import redis.asyncio as aioredis

        _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        await _redis.ping()
        logger.info("redis_connected", url=settings.REDIS_HOST)
    except Exception as e:  # noqa: BLE001
        logger.warning("redis_connect_failed", error=str(e))
        _redis = None
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


def _normalize(text: str) -> str:
    """问题归一化：小写、去空白、去标点（中英文）。"""
    text = text.lower().strip()
    text = re.sub(r"[\s，。？！、,.?!;:\"'`]+", "", text)
    return text


def cache_key(db_id: str, question: str) -> str:
    digest = hashlib.sha256(f"{db_id}::{_normalize(question)}".encode()).hexdigest()[:32]
    return f"qf:sql:{digest}"


async def get_cached(db_id: str, question: str) -> dict | None:
    redis = await get_redis()
    if redis is None:
        return None
    try:
        raw = await redis.get(cache_key(db_id, question))
    except Exception as e:  # noqa: BLE001
        logger.warning("cache_get_failed", error=str(e))
        return None
    if raw:
        cache_total.labels(result="hit").inc()
        return json.loads(raw)
    cache_total.labels(result="miss").inc()
    return None


async def set_cached(db_id: str, question: str, payload: dict) -> None:
    redis = await get_redis()
    if redis is None:
        return
    try:
        await redis.set(
            cache_key(db_id, question),
            json.dumps(payload, ensure_ascii=False),
            ex=settings.CACHE_TTL_SECONDS,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("cache_set_failed", error=str(e))
