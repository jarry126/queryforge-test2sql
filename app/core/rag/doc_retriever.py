"""业务文档检索 + summary 展开（对应手绘图①的 summary 特殊处理）.

并发检索 rag_chunk（table/text/summary）。summary 的处理与其它不同：
命中 summary 后，不直接用 summary 文本，而是取出其 metadata 中存放的 chunk_id 集合，
回表取回该页的全部原始 chunk，并入结果 —— 即「用 summary 当索引、用原文当上下文」。

最终对 table/text 原文 chunk 去重、重排，返回 top_n。
"""

from __future__ import annotations

from app.core.config import settings
from app.core.rag import reranker, retriever
from app.core.rag.vectorstore import fetch_chunks_by_ids


async def retrieve_docs(queries: list[str], top_k: int | None = None) -> list[dict]:
    """检索业务文档上下文。无文档时返回空列表（链路照常）。"""
    top_k = top_k or settings.RETRIEVE_TOP_K
    # 1) rag_chunk 混合检索（含 summary）
    candidates = await retriever.hybrid_search("rag_chunk", queries, db_id=None, top_k=top_k, do_rerank=False)
    if not candidates:
        return []

    content: dict[int, dict] = {}
    summary_chunk_ids: set[int] = set()
    for c in candidates:
        if c.get("chunk_type") == "summary":
            ids = (c.get("metadata") or {}).get("chunk_ids", [])
            summary_chunk_ids.update(int(i) for i in ids)
        else:
            content[c["id"]] = c

    # 2) summary 展开：取回其覆盖的整页原文 chunk
    expand_ids = [i for i in summary_chunk_ids if i not in content]
    for ch in await fetch_chunks_by_ids(expand_ids):
        content[ch["id"]] = ch

    merged = list(content.values())
    if not merged:
        return []

    # 3) 对原文 chunk 重排取 top_n
    return await reranker.rerank(queries[0], merged, top_n=settings.RERANK_TOP_N)
