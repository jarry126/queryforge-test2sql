"""无 RAG 的 text-to-SQL 路径（baseline，用于 A/B 对照）.

与完整 RAG 链路相对照：这里**不检索、不重排、不 few-shot、不多查询**，
直接把整库完整 schema（schema_doc 全量）+ 问题喂给 LLM 生成 SQL，再走同一套
安全校验(guard) + 沙箱执行(executor)。等价于"纯提示词控准确度"的传统做法。

目的：量化"有 RAG vs 无 RAG"在执行准确率上的差距。不接缓存、不接会话。
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage

from app.core.config import settings
from app.core.rag.vectorstore import fetch_full_schema
from app.schemas.query import QueryResponse
from app.services import llm
from app.sql.executor import execute
from app.sql.guard import SQLGuardError, validate_and_secure

NORAG_SQL_PROMPT = """你是一名 SQL 生成助手。根据用户问题和给定的【完整表结构】，生成一条可直接执行的 {dialect} SQL。

# 完整表结构（该库全部表）
{schema}

# 规则
- 只生成一条 SELECT 语句，禁止任何写操作（INSERT/UPDATE/DELETE/DDL）。
- 只使用上面表结构中出现的表名和列名，不得编造字段。
- 需要聚合/分组时正确使用 GROUP BY；多表 JOIN 用表别名。
- 直接输出 SQL，不要 markdown 围栏，不要解释。

# 问题
{question}

SQL："""

NORAG_CORRECTION_BLOCK = """

# 上一次尝试失败，请修正
上次 SQL：
{prev_sql}
错误信息：{error}
请生成修正后的 SQL，仍然只输出 SQL。"""


async def run_query_no_rag(question: str, db_id: str, max_retries: int = 0) -> QueryResponse:
    """无 RAG 单轮查询：整库 schema + 问题 → 生成 SQL → 校验 → 执行。

    max_retries 用于公平评测：让 noRAG baseline 也具备与 LangGraph 链路类似的
    校验/执行失败后自纠错能力。默认 0 保持原来的单次生成行为。
    """
    schema = await fetch_full_schema(db_id)
    if not schema:
        return QueryResponse(
            question=question, db_id=db_id, sql="", success=False,
            answer=f"未找到库 {db_id} 的 schema（先 make ingest）", language="zh",
            error="no_schema",
        )

    base_prompt = NORAG_SQL_PROMPT.format(dialect=settings.SQL_DIALECT, schema=schema, question=question)
    last_sql = ""
    last_error = ""

    for attempt in range(max_retries + 1):
        correction = ""
        if last_error:
            correction = NORAG_CORRECTION_BLOCK.format(prev_sql=last_sql or "（无）", error=last_error)
        prompt = f"{base_prompt}{correction}"

        try:
            sql_raw = await llm.ainvoke([HumanMessage(content=prompt)], temperature=0.0)
        except Exception as e:  # noqa: BLE001
            return QueryResponse(
                question=question, db_id=db_id, sql=last_sql, success=False,
                answer=f"LLM 生成失败：{e}", language="zh", attempts=attempt, error=str(e),
            )

        last_sql = sql_raw.strip()
        try:
            sql = validate_and_secure(last_sql, dialect=settings.SQL_DIALECT)
        except SQLGuardError as e:
            last_error = f"SQL 校验未通过：{e}"
            if attempt < max_retries:
                continue
            return QueryResponse(
                question=question, db_id=db_id, sql=last_sql, success=False,
                answer=last_error, language="zh", attempts=attempt, error=str(e),
            )

        result = await execute(db_id, sql)
        if result.ok:
            return QueryResponse(
                question=question, db_id=db_id, sql=sql,
                success=True, answer="(no-rag baseline)", language="zh",
                columns=result.columns, rows=result.rows, row_count=result.row_count,
                attempts=attempt,
            )
        last_sql = sql
        last_error = result.error or "SQL 执行失败"
        if attempt >= max_retries:
            return QueryResponse(
                question=question, db_id=db_id, sql=sql,
                success=False, answer=f"SQL 执行失败：{last_error}", language="zh",
                columns=result.columns, rows=result.rows, row_count=result.row_count,
                attempts=attempt, error=last_error,
            )

    return QueryResponse(
        question=question, db_id=db_id, sql=last_sql, success=False,
        answer=f"SQL 生成失败：{last_error}", language="zh", attempts=max_retries, error=last_error,
    )
