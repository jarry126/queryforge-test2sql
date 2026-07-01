"""应用主入口.

装配 FastAPI：生命周期（连接池 / Redis / 图预热）、中间件（correlation-id / CORS）、
限流处理器、Prometheus /metrics、v1 路由。
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from asgi_correlation_id import CorrelationIdMiddleware, correlation_id
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded

from app.api.v1.api import api_router
from app.core.cache import close_redis, get_redis
from app.core.config import settings
from app.core.db import close_pool, get_pool
from app.core.errors import classify
from app.core.langgraph.graph import get_graph
from app.core.limiter import limiter
from app.core.logging import logger
from app.core.metrics import metrics_app
from app.core.middleware import LoggingContextMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("startup", project=settings.PROJECT_NAME, version=settings.VERSION, env=settings.APP_ENV.value)
    # 预热连接池 / Redis / 图，避免首请求承担冷启动
    try:
        await get_pool()
    except Exception as e:  # noqa: BLE001
        logger.exception("pool_init_failed", error=str(e))
    try:
        await get_redis()
    except Exception as e:  # noqa: BLE001
        logger.warning("redis_init_failed", error=str(e))
    try:
        await get_graph()
        logger.info("graph_prewarmed")
    except Exception as e:  # noqa: BLE001
        logger.exception("graph_prewarm_failed", error=str(e))
    yield
    # 关停前刷一次 Langfuse，确保缓冲中的 trace 上报完
    try:
        if settings.LANGFUSE_ENABLED:
            from langfuse import get_client

            get_client().flush()
    except Exception as e:  # noqa: BLE001
        logger.warning("langfuse_flush_failed", error=str(e))
    await close_redis()
    await close_pool()
    logger.info("shutdown")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description=settings.DESCRIPTION,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan,
)

# Prometheus 指标
app.mount("/metrics", metrics_app)

# 限流
app.state.limiter = limiter


async def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    logger.warning("rate_limited", path=request.url.path, limit=str(exc.detail))
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={"detail": "请求过于频繁，请稍后再试", "limit": str(exc.detail)},
    )


app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)  # type: ignore[arg-type]


@app.exception_handler(RequestValidationError)
async def _validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = [
        {"field": " -> ".join(str(p) for p in e["loc"] if p != "body"), "message": e["msg"]}
        for e in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": "参数校验失败", "errors": errors})


@app.exception_handler(Exception)
async def _global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """全局兜底：任何未被业务处理的异常 → 分类 + 友好文案 + request_id，不泄漏内部细节。

    限流→429、上游不可用/熔断→503、未知→500。完整堆栈进日志（带 request_id 可追溯）。
    """
    err = classify(exc)
    rid = correlation_id.get() or "-"
    logger.exception(
        "unhandled_exception", category=err.category, path=request.url.path, status_code=err.status_code
    )
    headers = {"Retry-After": "5"} if err.status_code in (429, 503) else None
    return JSONResponse(
        status_code=err.status_code,
        content={"detail": err.user_message, "category": err.category, "request_id": rid},
        headers=headers,
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# 中间件按 LIFO 执行：先 add 的后执行。CorrelationId 最后 add → 最先执行，
# 保证 request_id 在 LoggingContext 记录日志前已就绪。
app.add_middleware(LoggingContextMiddleware)
app.add_middleware(CorrelationIdMiddleware)

app.include_router(api_router, prefix=settings.API_V1_STR)

# 挂载原生单页前端（登录/历史会话/多轮聊天），访问 http://localhost:8000/ui/
_static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
if os.path.isdir(_static_dir):
    app.mount("/ui", StaticFiles(directory=_static_dir, html=True), name="ui")


@app.get("/")
async def root() -> dict:
    return {
        "name": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "status": "ok",
        "ui": "/ui/",
        "docs": "/docs",
    }
