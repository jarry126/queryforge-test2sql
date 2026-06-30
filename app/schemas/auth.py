"""鉴权与会话相关的请求/响应模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=6, max_length=128)


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str


class UserInfo(BaseModel):
    id: int
    username: str


class CreateSessionRequest(BaseModel):
    db_id: str = Field(min_length=1)
    title: str = "新会话"


class SessionInfo(BaseModel):
    id: str
    title: str
    db_id: str
    updated_at: str | None = None


class ChatRequest(BaseModel):
    question: str = Field(min_length=1)


class ChatMessage(BaseModel):
    role: str
    content: str
    sql: str | None = None
    result: dict | None = None
    turn_id: str | None = None
