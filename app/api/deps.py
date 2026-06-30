"""API 依赖：当前登录用户。"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.security import decode_access_token

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict:
    """解析 Bearer token，返回 {id, username}；失败抛 401。"""
    if cred is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")
    try:
        payload = decode_access_token(cred.credentials)
        return {"id": int(payload["sub"]), "username": payload.get("username")}
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已失效，请重新登录") from None


async def get_optional_user(
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict | None:
    """解析可选 Bearer token；无 token 返回 None，非法 token 返回 401。"""
    if cred is None:
        return None
    try:
        payload = decode_access_token(cred.credentials)
        return {"id": int(payload["sub"]), "username": payload.get("username")}
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已失效，请重新登录") from None
