"""节点：Schema Linking.

把检索到的 schema 文档（已重排/剪枝）裁剪、拼装为喂给 LLM 的紧凑 schema 文本。
RAG 召回本身即完成「相关表/列裁剪」——只保留与问题相关的表，降 token、提准确率。
"""

from __future__ import annotations

from app.core.langgraph.state import GraphState
from app.core.logging import logger


async def schema_linking(state: GraphState) -> dict:
    docs = state.get("schema_docs", [])
    # 优先保留表级文档；库级概览放最前作为上下文
    db_docs = [d for d in docs if d.get("doc_type") == "db"]
    table_docs = [d for d in docs if d.get("doc_type") == "table"]

    parts: list[str] = []
    if db_docs:
        parts.append(db_docs[0]["content"])
    seen: set[str] = set()
    for d in table_docs:
        name = d.get("table_name") or ""
        if name in seen:
            continue
        seen.add(name)
        parts.append(d["content"])

    linked = "\n\n".join(parts) if parts else "（未检索到相关 schema）"
    logger.info(
        "schema_linking",
        tables=sorted(seen),
        table_count=len(seen),
        schema_chars=len(linked),
    )
    # linked = schema表中： db库 content 集合 + table表 content 集合
    return {"linked_schema": linked}
