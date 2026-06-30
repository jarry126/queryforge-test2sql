"""横切中间件：把请求上下文绑定到日志，并记录请求开始/完成。

- 从 Authorization 解出 user_id，绑定到日志上下文（该请求所有日志自动带 user_id），
  同时写入 request.state.user_id 供限流器按用户限流。
- 记录"收到请求/请求完成"（含方法/路径/状态/耗时；POST body 脱敏后记录）。
- /metrics 路径跳过日志，避免污染。
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import bind_context, clear_context, logger
from app.core.security import decode_access_token

_SENSITIVE = {"password", "token", "secret", "api_key", "access_token", "jwt_secret"}


class LoggingContextMiddleware(BaseHTTPMiddleware):
    """请求级日志上下文 + 请求/响应日志。"""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start = time.time()
        status_code = 500
        path = request.url.path
        method = request.method
        skip = path.startswith("/metrics")

        try:
            clear_context()

            # 解析 JWT，绑定 user_id
            auth = request.headers.get("authorization")
            if auth and auth.startswith("Bearer "):
                try:
                    payload = decode_access_token(auth.split(" ", 1)[1])
                    if uid := payload.get("sub"):
                        bind_context(user_id=uid)
                        request.state.user_id = uid
                except Exception:  # noqa: BLE001 - token 无效交给鉴权依赖处理
                    pass

            if not skip:
                body_for_log = await _read_body_for_log(request, method)
                logger.info(
                    "收到请求",
                    parameters={
                        k: v
                        for k, v in {
                            "method": method,
                            "path": path,
                            "query": dict(request.query_params) or None,
                            "body": body_for_log,
                            "client": request.client.host if request.client else None,
                        }.items()
                        if v is not None
                    },
                )

            response = await call_next(request)
            status_code = response.status_code
            return response
        except Exception:
            status_code = 500
            raise
        finally:
            if not skip:
                logger.info(
                    "请求完成",
                    parameters={
                        "method": method,
                        "path": path,
                        "status": status_code,
                        "duration_ms": round((time.time() - start) * 1000, 2),
                    },
                )
            clear_context()


async def _read_body_for_log(request: Request, method: str) -> dict | list | None:
    """读取并脱敏 JSON body（Starlette 会缓存 body，后续 handler 仍可读取）。"""
    if method not in ("POST", "PUT", "PATCH"):
        return None
    if "application/json" not in request.headers.get("content-type", ""):
        return None
    try:
        raw = await request.body()
        if not raw:
            return None
        data = json.loads(raw.decode("utf-8"))
        if isinstance(data, dict):
            return {k: ("***" if k.lower() in _SENSITIVE else v) for k, v in data.items()}
        return data
    except Exception:  # noqa: BLE001
        return None
