"""v1 API 路由汇总。"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import auth, health, ingest, query, sessions

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(sessions.router)
api_router.include_router(query.router)
api_router.include_router(ingest.router)
