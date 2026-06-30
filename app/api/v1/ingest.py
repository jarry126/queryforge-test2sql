"""POST /ingest — 业务文档上传与切块入库（对应手绘图②）。

接收纯文本/Markdown，按图②切块（table/text），LLM 按页生成 summary，
summary 存所覆盖的 chunk_id 集合，全部写入 rag_chunk（向量 + 全文）。
PDF 解析 / 物理分页在 Phase 2.x 后续完善。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import get_current_user
from app.core.config import settings
from app.services.ingest import ingest_document

router = APIRouter(tags=["ingest"])


class IngestRequest(BaseModel):
    doc_id: str = Field(min_length=1)
    text: str = Field(min_length=1)


class IngestResponse(BaseModel):
    doc_id: str
    content_chunks: int
    summaries: int


@router.post("/ingest", response_model=IngestResponse)
async def ingest(body: IngestRequest, user: dict = Depends(get_current_user)) -> IngestResponse:
    """对上传文本切块、汇总并入库。"""
    if len(body.text) > settings.INGEST_MAX_CHARS:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"文档过大，最大允许 {settings.INGEST_MAX_CHARS} 字符",
        )
    stats = await ingest_document(body.doc_id, body.text)
    return IngestResponse(**stats)
