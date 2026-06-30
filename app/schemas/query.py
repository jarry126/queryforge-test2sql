"""/query 接口的请求与响应模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class HistoryTurn(BaseModel):
    role: str = Field(description="user | assistant")
    content: str


class QueryRequest(BaseModel):
    question: str = Field(min_length=1, description="自然语言问题")
    db_id: str = Field(min_length=1, description="目标数据库标识")
    thread_id: str | None = Field(default=None, description="会话 id，用于多轮 checkpoint")
    history: list[HistoryTurn] = Field(default_factory=list, description="可选历史（无 thread_id 时使用）")


class QueryResponse(BaseModel):
    question: str
    db_id: str
    sql: str
    success: bool
    answer: str
    language: str
    columns: list[str] = Field(default_factory=list)
    rows: list[list] = Field(default_factory=list)
    row_count: int = 0
    attempts: int = 0
    from_cache: bool = False
    error: str | None = None
