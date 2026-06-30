"""节点：基于历史改写问题（对应图①「根据 N 轮历史上下文重写问题」）。"""

from __future__ import annotations

from langchain_core.messages import HumanMessage

from app.core.config import settings
from app.core.langgraph.prompts import REWRITE_PROMPT
from app.core.langgraph.state import GraphState
from app.core.logging import logger
from app.services import llm


def _format_history(history: list[dict], turns: int) -> str:
    """取最近 turns 轮历史（{role, content} 列表），格式化为文本。"""
    recent = history[-turns * 2 :] if history else []
    lines = [f"{m.get('role', 'user')}: {m.get('content', '')}" for m in recent]
    return "\n".join(lines) if lines else "（无历史）"


async def rewrite(state: GraphState) -> dict:
    question = state["question"]
    history = state.get("history", [])
    # 无历史时直接用原问题，省一次 LLM 调用
    if not history:
        return {"rewritten_question": question}
    prompt = REWRITE_PROMPT.format(
        history=_format_history(history, settings.HISTORY_TURNS), question=question
    )
    try:
        rewritten = await llm.ainvoke([HumanMessage(content=prompt)])
        rewritten = rewritten.strip() or question
    except Exception as e:  # noqa: BLE001
        logger.warning("rewrite_failed_fallback", error=str(e))
        rewritten = question
    logger.info("rewrite", original=question, rewritten=rewritten, history_turns=len(history) // 2)
    return {"rewritten_question": rewritten}
