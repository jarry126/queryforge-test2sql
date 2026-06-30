"""接口限流（slowapi）.

- 已登录用户按 user_id 限流，未登录降级为按 IP。
- 配置 Redis 后使用分布式存储，多副本部署计数共享（满足 100 QPS 多 Pod 场景）。
"""

from __future__ import annotations

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings


def _rate_key(request: Request) -> str:
    """限流维度：优先 user_id，兜底客户端 IP。"""
    user_id = getattr(request.state, "user_id", None)
    if user_id:
        return f"user:{user_id}"
    return get_remote_address(request)


limiter = Limiter(
    key_func=_rate_key,
    default_limits=[settings.RATE_LIMIT_DEFAULT],
    storage_uri=settings.redis_url if settings.REDIS_ENABLED else "memory://",
    strategy="moving-window",
)
