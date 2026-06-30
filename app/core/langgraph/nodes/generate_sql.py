"""节点：生成 SQL（LLM）。

依据 问题 + linked schema + few-shot 示例生成单条 SQL。
自纠错时携带上次失败的 SQL 与错误信息（CORRECTION_BLOCK）。
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage

from app.core.config import settings
from app.core.langgraph.prompts import CORRECTION_BLOCK, GENERATE_SQL_PROMPT
from app.core.langgraph.state import GraphState
from app.core.logging import logger
from app.core.metrics import llm_calls_total, llm_latency_seconds
from app.services import llm


def _format_fewshots(fewshots: list[dict]) -> str:
    if not fewshots:
        return "（无）"
    return "\n".join(f"Q: {f['question']}\nSQL: {f['sql']}" for f in fewshots)


def _format_business(docs: list[dict]) -> str:
    if not docs:
        return "（无）"
    return "\n".join(f"- {d['content']}" for d in docs[:5])


async def generate_sql(state: GraphState) -> dict:
    question = state.get("rewritten_question") or state["question"]
    correction = ""
    if state.get("error") and state.get("sql"):
        correction = CORRECTION_BLOCK.format(prev_sql=state["sql"], error=state["error"])

    prompt = GENERATE_SQL_PROMPT.format(
        dialect=settings.SQL_DIALECT,
        schema=state.get("linked_schema", ""),
        fewshots=_format_fewshots(state.get("fewshots", [])),
        business=_format_business(state.get("doc_context", [])),
        correction=correction,
        question=question,
    )
    attempt = state.get("attempt", 0)
    # DEBUG 时打印喂给 LLM 的完整 prompt（schema + few-shot + 问题），定位"答案不理想"的根因
    logger.debug("generate_sql_prompt", prompt=prompt)
    with llm_latency_seconds.labels(node="generate_sql").time():
        try:
            sql = await llm.ainvoke([HumanMessage(content=prompt)], temperature=0.0)
            llm_calls_total.labels(node="generate_sql", status="ok").inc()
        except Exception as e:  # noqa: BLE001
            llm_calls_total.labels(node="generate_sql", status="error").inc()
            logger.error("generate_sql_failed", error=str(e), attempt=attempt)
            return {"error": f"LLM 生成失败: {e}", "sql": ""}
    sql = sql.strip()
    logger.info(
        "generate_sql",
        question=question,
        sql=sql,
        attempt=attempt,
        is_correction=bool(correction),
        fewshots=len(state.get("fewshots", [])),
        schema_chars=len(state.get("linked_schema", "")),
    )
    return {"sql": sql, "error": None}
