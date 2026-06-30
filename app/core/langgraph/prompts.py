"""链路各节点的提示词（集中管理，便于后续接 Langfuse Prompt 管理）。"""

from __future__ import annotations

REWRITE_PROMPT = """你是查询改写助手。结合最近的对话历史，把用户最新的问题改写成一个**自包含、明确**的问题，用于数据库检索与 SQL 生成。
- 补全指代（如"它""这些"）与省略的主体。
- 不要回答问题，只输出改写后的问题本身，不加任何解释。

对话历史：
{history}

用户最新问题：{question}

改写后的问题："""

EXPAND_PROMPT = """针对下面的问题，生成 {n} 个语义等价但措辞不同的检索改写问，用于提升召回。
每行一个，不要编号，不要解释。

问题：{question}"""

GENERATE_SQL_PROMPT = """你是资深数据分析师，负责把自然语言问题转成**单条只读 SQL 查询**（{dialect} 方言）。

# 数据库 Schema
{schema}

# 相似示例（参考其写法，不要照抄表名/列名）
{fewshots}

# 业务知识（列含义/指标口径/取值映射，若与 schema 冲突以 schema 为准）
{business}

# 规则
- 只生成一条 SELECT 语句，禁止任何写操作（INSERT/UPDATE/DELETE/DDL）。
- 只使用上面 Schema 中出现的表名和列名。
- 需要聚合/分组时正确使用 GROUP BY；需要排序时给出 ORDER BY。
- 直接输出 SQL，不要 markdown 围栏，不要解释。
{correction}

# 问题
{question}

SQL："""

CORRECTION_BLOCK = """
# 上一次尝试失败，请修正
上次 SQL：
{prev_sql}
错误信息：{error}
请生成修正后的 SQL。"""

SUMMARY_PROMPT = """请对下面同一页/小节的若干文档片段做要点总结，输出一段不超过 200 字的中文摘要，
覆盖其中的关键实体、指标与口径，供后续检索定位整页内容使用。只输出摘要本身。

片段：
{content}

摘要："""

ANSWER_PROMPT = """根据下面的查询结果，用「{language}」自然语言简洁回答用户的问题。
- 直接给出结论，必要时列出关键数据。
- 不要编造结果中没有的数据。

用户问题：{question}
执行的 SQL：{sql}
查询结果（列：{columns}）：
{rows}

回答："""
