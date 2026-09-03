"""问答反馈请求/响应模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class FeedbackRequest(BaseModel):
    rating: Literal["up", "down"]
    comment: str | None = Field(default=None, max_length=2000)


class FeedbackInfo(BaseModel):
    id: int
    message_id: int
    session_id: str
    rating: Literal["up", "down"]
    comment: str | None = None
    question_text: str = ""
    created_at: str | None = None
    updated_at: str | None = None
