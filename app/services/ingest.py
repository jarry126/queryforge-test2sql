"""业务文档入库编排（对应手绘图②完整链路）.

流程：
1. 拆分文档 → table/text chunk（按标题切，超 1000 字符语义/字符兜底切割）；
2. 写入 rag_chunk（向量 + pg_jieba 全文），拿回各 chunk 的 id；
3. 按「页」分组（无物理分页时按 PAGE_CHUNK_SIZE 个 chunk 归为一页），
   对每页用 LLM 生成 summary；
4. summary 作为一条 summary 类型 chunk 写入，metadata 存该页 chunk_id 集合
   —— 供检索阶段命中 summary 后展开取回整页内容（图①的 summary 特殊处理）。

image 类型当前不处理（与手绘图一致），预留入口。
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage

from app.core.langgraph.prompts import SUMMARY_PROMPT
from app.core.logging import logger
from app.core.rag.ingest import chunk_markdown, paginate
from app.core.rag.vectorstore import upsert_rag_chunks
from app.services import llm

PAGE_CHUNK_SIZE = 5  # 无物理分页时，多少个内容 chunk 归为「一页」做一次 summary


async def _summarize(texts: list[str]) -> str:
    """对一页内容生成 summary；LLM 失败时退化为标题/首句拼接。"""
    joined = "\n---\n".join(texts)[:4000]
    try:
        return (await llm.ainvoke([HumanMessage(content=SUMMARY_PROMPT.format(content=joined))])).strip()
    except Exception as e:  # noqa: BLE001
        logger.warning("summary_llm_failed_fallback", error=str(e))
        return "本页要点：" + "；".join(t[:40] for t in texts)


async def ingest_document(doc_id: str, text: str, page_size: int = PAGE_CHUNK_SIZE) -> dict:
    """落库一篇业务文档，返回统计信息。"""
    chunks = chunk_markdown(text)
    if not chunks:
        return {"doc_id": doc_id, "content_chunks": 0, "summaries": 0}

    # 1) 写内容 chunk，拿回 id
    content_rows = [
        {"doc_id": doc_id, "chunk_type": c.chunk_type, "page": idx // page_size,
         "content": c.content, "metadata": c.metadata}
        for idx, c in enumerate(chunks)
    ]
    content_ids = await upsert_rag_chunks(content_rows)

    # 2) 按页生成 summary，metadata 存该页 chunk_id 集合
    summary_rows = []
    for page, idx_group in enumerate(paginate(len(chunks), page_size)):
        page_ids = [content_ids[i] for i in idx_group]
        summary_text = await _summarize([chunks[i].content for i in idx_group])
        summary_rows.append(
            {
                "doc_id": doc_id,
                "chunk_type": "summary",
                "page": page,
                "content": summary_text,
                "metadata": {"chunk_ids": page_ids},  # 图②：summary 存 chunk_id 集合
            }
        )
    await upsert_rag_chunks(summary_rows)

    logger.info("doc_ingested", doc_id=doc_id, content=len(content_ids), summaries=len(summary_rows))
    return {"doc_id": doc_id, "content_chunks": len(content_ids), "summaries": len(summary_rows)}
