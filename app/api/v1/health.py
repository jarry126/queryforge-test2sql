"""健康检查。"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.db import health_check

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> JSONResponse:
    db_ok = await health_check()
    body = {
        "status": "healthy" if db_ok else "degraded",
        "version": settings.VERSION,
        "environment": settings.APP_ENV.value,
        "components": {"api": "healthy", "database": "healthy" if db_ok else "unhealthy"},
        "timestamp": datetime.now().isoformat(),
    }
    code = status.HTTP_200_OK if db_ok else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(content=body, status_code=code)


@router.get("/live")
async def live() -> dict:
    """Kubernetes liveness probe：只表示进程仍可响应，不依赖外部组件。"""
    return {
        "status": "alive",
        "version": settings.VERSION,
        "environment": settings.APP_ENV.value,
        "timestamp": datetime.now().isoformat(),
    }


@router.get("/ready")
async def ready() -> JSONResponse:
    """Kubernetes readiness probe：依赖核心数据库，失败时摘出流量。"""
    db_ok = await health_check()
    body = {
        "status": "ready" if db_ok else "not_ready",
        "version": settings.VERSION,
        "environment": settings.APP_ENV.value,
        "components": {"database": "healthy" if db_ok else "unhealthy"},
        "timestamp": datetime.now().isoformat(),
    }
    code = status.HTTP_200_OK if db_ok else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(content=body, status_code=code)
