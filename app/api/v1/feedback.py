"""问答反馈接口：提交、查看单条、列出当前用户反馈。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_current_user
from app.schemas.feedback import FeedbackInfo, FeedbackRequest
from app.services import feedback_store

router = APIRouter(tags=["feedback"])


@router.put(
    "/sessions/{session_id}/messages/{message_id}/feedback",
    response_model=FeedbackInfo,
)
async def upsert_feedback(
    session_id: str,
    message_id: int,
    body: FeedbackRequest,
    user: dict = Depends(get_current_user),
) -> FeedbackInfo:
    message = await feedback_store.get_message_for_user(session_id, message_id, user["id"])
    if not message:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="消息不存在或不可反馈")

    comment = body.comment.strip() if body.comment else None
    if comment == "":
        comment = None

    row = await feedback_store.upsert_feedback(
        message_id=message_id,
        user_id=user["id"],
        session_id=session_id,
        rating=body.rating,
        comment=comment,
        question_text=message["question_text"] or "",
    )
    return FeedbackInfo(**row)


@router.get(
    "/sessions/{session_id}/messages/{message_id}/feedback",
    response_model=FeedbackInfo,
)
async def get_feedback(
    session_id: str,
    message_id: int,
    user: dict = Depends(get_current_user),
) -> FeedbackInfo:
    message = await feedback_store.get_message_for_user(session_id, message_id, user["id"])
    if not message:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="消息不存在或不可反馈")
    row = await feedback_store.get_feedback(message_id, user["id"])
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="尚未提交反馈")
    return FeedbackInfo(**row)


@router.get("/feedback", response_model=list[FeedbackInfo])
async def list_feedback(
    rating: str | None = Query(default=None, pattern="^(up|down)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: dict = Depends(get_current_user),
) -> list[FeedbackInfo]:
    """查询当前用户提交的反馈（含问题快照），便于排查与改进。"""
    rows = await feedback_store.list_feedback_for_user(
        user["id"], rating=rating, limit=limit, offset=offset
    )
    return [FeedbackInfo(**r) for r in rows]
