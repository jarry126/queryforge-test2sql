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
