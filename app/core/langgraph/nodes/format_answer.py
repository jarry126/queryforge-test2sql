"""节点：组装回答 / 报错（对应图①「组装上下文返回」与「报错」）。"""

from __future__ import annotations

from langchain_core.messages import HumanMessage

from app.core.config import settings
from app.core.langgraph.prompts import ANSWER_PROMPT
from app.core.langgraph.state import GraphState
from app.core.logging import logger
from app.services import llm

_MAX_ROWS_IN_PROMPT = 30


def _format_rows(columns: list[str], rows: list[list]) -> str:
    if not rows:
        return "（无数据）"
    head = rows[:_MAX_ROWS_IN_PROMPT]
    lines = [" | ".join(str(c) for c in r) for r in head]
    more = f"\n…（共 {len(rows)} 行，已截断）" if len(rows) > _MAX_ROWS_IN_PROMPT else ""
    return "\n".join(lines) + more


async def format_answer(state: GraphState) -> dict:
    result = state.get("sql_result", {})
    question = state["question"]
    sql = state.get("sql", "")
    language = state.get("language", "zh")

    if not result.get("ok"):
        # 多次自纠错后仍失败：返回失败说明，不编造结果
        answer = f"抱歉，未能生成可执行的 SQL。最后一次错误：{state.get('error')}"
        logger.warning("answer_failed", error=state.get("error"), sql=sql, attempts=state.get("attempt", 0))
        return {"answer": answer, "success": False}

    if settings.EVAL_SKIP_ANSWER_LLM:
        answer = f"查询成功，共 {result.get('row_count', 0)} 行。"
        logger.info("answer_eval_skipped", sql=sql, row_count=result.get("row_count", 0))
        return {"answer": answer, "success": True}

    prompt = ANSWER_PROMPT.format(
        language=language,
        question=question,
        sql=sql,
        columns=", ".join(result.get("columns", [])),
        rows=_format_rows(result.get("columns", []), result.get("rows", [])),
    )
    try:
        answer = await llm.ainvoke([HumanMessage(content=prompt)])
    except Exception as e:  # noqa: BLE001
        logger.warning("answer_format_failed", error=str(e))
        answer = f"查询成功，共 {result.get('row_count', 0)} 行。SQL：{sql}"
    answer = answer.strip()
    logger.info(
        "answer_ok",
        sql=sql,
        row_count=result.get("row_count", 0),
        attempts=state.get("attempt", 0),
        answer=answer[:300],
    )
    return {"answer": answer, "success": True}


async def error_node(state: GraphState) -> dict:
    """检索为空时的报错出口（图①「有结果? 没有→报错」）。"""
    msg = "未检索到与问题相关的库表信息，无法生成 SQL。请补充更多上下文或确认数据库。"
    logger.info("no_context_error", db_id=state.get("db_id"))
    return {"answer": msg, "success": False}
