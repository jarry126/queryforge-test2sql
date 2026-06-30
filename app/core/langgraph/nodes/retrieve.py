"""节点：并发混合检索（对应图①「3 个问题并发检索 → 去重剪枝 → 重排」）。

并发检索三类语料：
- schema_doc：用于 schema linking 与 SQL 生成；
- fewshot_example：相似 NL->SQL 示例；
- rag_chunk：业务文档（含 summary 特殊展开，图①）。
各自走 向量+关键词 混合检索 + RRF + rerank。
"""

from __future__ import annotations

import asyncio

from app.core.config import settings
from app.core.langgraph.state import GraphState
from app.core.logging import logger
from app.core.rag import doc_retriever, retriever


async def retrieve(state: GraphState) -> dict:
    db_id = state.get("db_id")
    primary = state.get("rewritten_question") or state["question"]
    queries = [primary, *state.get("expanded_queries", [])]

    schema_task = retriever.hybrid_search(
        "schema_doc", queries, db_id=db_id, top_k=settings.RETRIEVE_TOP_K, do_rerank=True
    )
    # few-shot 可跨库：教模型 SQL 写法/句式（跨库通用），不强求同库。
    # 单库生产下 db_id 只有一个、跨库=同库；CSpider 跨域评测靠这个激活 few-shot。
    fewshot_db = None if settings.FEWSHOT_CROSS_DB else db_id
    fewshot_task = retriever.hybrid_search(
        "fewshot_example", queries, db_id=fewshot_db, top_k=settings.FEWSHOT_TOP_K, do_rerank=False
    )
    doc_task = (
        doc_retriever.retrieve_docs(queries, top_k=settings.RETRIEVE_TOP_K)
        if settings.DOC_CONTEXT_ENABLED
        else _empty_docs()
    )
    # 检索调用异常（embedding/向量库/ES 故障）直接上抛，由全局兜底分类为 503，
    # 而不是吞成"空结果"——否则会把后端故障误报成"未检索到相关库表"。
    # 真正的"无匹配"是 gather 正常返回但结果为空，会走 error_node。
    try:
        schema_docs, fewshots, docs = await asyncio.gather(schema_task, fewshot_task, doc_task)
    except Exception:
        logger.exception("retrieve_failed")
        raise

    # 关键调试信息：召回了哪些表（带分数），用于判断 schema linking 是否拉对了表
    def _preview(d: dict) -> dict:
        return {
            "table": d.get("table_name") or d.get("doc_type"),
            "score": round(d.get("rerank_score") or d.get("rrf_score") or d.get("_vscore") or 0, 4),
        }

    logger.info(
        "retrieved",
        db_id=db_id,
        queries=queries,
        schema_count=len(schema_docs),
        fewshots_count=len(fewshots),
        docs_count=len(docs),
        schema_top=[_preview(d) for d in schema_docs[:8]],
        fewshot_questions=[f.get("question") for f in fewshots[: settings.FEWSHOT_TOP_K]],
    )
    return {
        "schema_docs": schema_docs,
        "fewshots": fewshots[: settings.FEWSHOT_TOP_K],
        "doc_context": docs,
    }


async def _empty_docs() -> list[dict]:
    return []
