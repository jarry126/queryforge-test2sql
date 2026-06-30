"""POST /query — 自然语言转 SQL 并执行。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.deps import get_optional_user
from app.core.config import settings
from app.core.inflight import query_inflight_slot
from app.core.limiter import limiter
from app.schemas.query import QueryRequest, QueryResponse
from app.services.text2sql import run_query

router = APIRouter(tags=["query"])


@router.post("/query", response_model=QueryResponse)
@limiter.shared_limit(settings.RATE_LIMIT_QUERY_GLOBAL, scope="query-global")
@limiter.limit(settings.RATE_LIMIT_QUERY)
async def query(request: Request, body: QueryRequest, user: dict | None = Depends(get_optional_user)) -> QueryResponse:
    """把自然语言问题转成 SQL、安全校验、沙箱执行并返回自然语言回答。"""
    if not settings.PUBLIC_QUERY_ENABLED and user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")
    async with query_inflight_slot():
        return await run_query(body)
