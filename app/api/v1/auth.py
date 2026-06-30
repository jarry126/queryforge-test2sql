"""鉴权接口：注册 / 登录 / 当前用户。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user
from app.core.security import create_access_token, hash_password, verify_password
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserInfo
from app.services import auth_store

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse)
async def register(body: RegisterRequest) -> TokenResponse:
    if await auth_store.get_user_by_username(body.username):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="用户名已存在")
    user = await auth_store.create_user(body.username, hash_password(body.password))
    token = create_access_token(user["id"], user["username"])
    return TokenResponse(access_token=token, username=user["username"])


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest) -> TokenResponse:
    user = await auth_store.get_user_by_username(body.username)
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    token = create_access_token(user["id"], user["username"])
    return TokenResponse(access_token=token, username=user["username"])


@router.get("/me", response_model=UserInfo)
async def me(user: dict = Depends(get_current_user)) -> UserInfo:
    return UserInfo(id=user["id"], username=user["username"])
