"""节点：多查询扩展（对应图①「再生成类似问题 a 和 b」）。"""

from __future__ import annotations

from langchain_core.messages import HumanMessage

from app.core.config import settings
from app.core.langgraph.prompts import EXPAND_PROMPT
from app.core.langgraph.state import GraphState
from app.core.logging import logger
from app.services import llm


async def expand(state: GraphState) -> dict:
    if not settings.QUERY_EXPANSION_ENABLED:
        return {"expanded_queries": []}
    question = state.get("rewritten_question") or state["question"]
    prompt = EXPAND_PROMPT.format(n=2, question=question)
    try:
        text = await llm.ainvoke([HumanMessage(content=prompt)], temperature=0.5)
        extras = [line.strip("-• ").strip() for line in text.splitlines() if line.strip()]
        extras = [e for e in extras if e][:2]
    except Exception as e:  # noqa: BLE001
        logger.warning("expand_failed", error=str(e))
        extras = []
    logger.info("expand", expanded=extras)
    return {"expanded_queries": extras}
