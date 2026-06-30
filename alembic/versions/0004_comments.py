"""为所有表与字段补充数据库注释（COMMENT ON）

Revision ID: 0004_comments
Revises: 0003_auth_sessions
Create Date: 2026-06-25

让 DBeaver / pgAdmin / psql \\d+ 能直接看到表和字段的中文备注。
"""

from __future__ import annotations

from alembic import op

revision = "0004_comments"
down_revision = "0003_auth_sessions"
branch_labels = None
depends_on = None

# (对象, 注释) 列表；表用 'TABLE 名'，字段用 'COLUMN 表.字段'
_COMMENTS: list[tuple[str, str]] = [
    # ---------- schema_doc：schema 文档语料 ----------
    ("TABLE schema_doc", "RAG 语料：库/表/列粒度的 schema 文档，供 schema linking 与生成 SQL 检索"),
    ("COLUMN schema_doc.id", "主键"),
    ("COLUMN schema_doc.db_id", "所属数据库标识"),
    ("COLUMN schema_doc.doc_type", "文档粒度：db(库概览) | table(表) | column(列)"),
    ("COLUMN schema_doc.table_name", "表名（doc_type=table 时有值）"),
    ("COLUMN schema_doc.content", "可检索文本，也是喂给 LLM 的 schema 描述"),
    ("COLUMN schema_doc.embedding", "content 的向量（pgvector，cosine 检索）"),
    ("COLUMN schema_doc.tsv", "content 的中文全文索引（pg_jieba 分词）"),
    ("COLUMN schema_doc.metadata", "附加信息（如列名集合）"),
    ("COLUMN schema_doc.created_at", "创建时间"),
    # ---------- fewshot_example：NL→SQL 示例 ----------
    ("TABLE fewshot_example", "RAG 语料：相似问题→SQL 的 few-shot 示例库"),
    ("COLUMN fewshot_example.id", "主键"),
    ("COLUMN fewshot_example.db_id", "所属数据库标识"),
    ("COLUMN fewshot_example.question", "自然语言问题"),
    ("COLUMN fewshot_example.sql", "对应的 gold SQL"),
    ("COLUMN fewshot_example.embedding", "question 的向量"),
    ("COLUMN fewshot_example.tsv", "question 的中文全文索引"),
    ("COLUMN fewshot_example.created_at", "创建时间"),
    # ---------- rag_chunk：业务文档块 ----------
    ("TABLE rag_chunk", "RAG 语料：上传业务文档切出的块（table/text/image/summary）"),
    ("COLUMN rag_chunk.id", "主键"),
    ("COLUMN rag_chunk.doc_id", "所属文档标识"),
    ("COLUMN rag_chunk.chunk_type", "块类型：table | text | image | summary"),
    ("COLUMN rag_chunk.page", "页码/小节序号"),
    ("COLUMN rag_chunk.content", "块文本内容"),
    ("COLUMN rag_chunk.embedding", "content 的向量"),
    ("COLUMN rag_chunk.tsv", "content 的中文全文索引"),
    ("COLUMN rag_chunk.metadata", "附加信息；summary 块在此存所覆盖的 chunk_id 集合"),
    ("COLUMN rag_chunk.created_at", "创建时间"),
    # ---------- query_cache：语义近似缓存 ----------
    ("TABLE query_cache", "语义近似缓存：问题向量→响应，命中同义问题直接返回（默认关闭）"),
    ("COLUMN query_cache.id", "主键"),
    ("COLUMN query_cache.db_id", "目标数据库标识"),
    ("COLUMN query_cache.question", "原始问题"),
    ("COLUMN query_cache.embedding", "问题向量，用于近邻匹配"),
    ("COLUMN query_cache.response", "缓存的完整响应(JSON)"),
    ("COLUMN query_cache.created_at", "写入时间，配合 TTL 过期"),
    # ---------- app_user：用户 ----------
    ("TABLE app_user", "应用用户（JWT 登录）"),
    ("COLUMN app_user.id", "主键"),
    ("COLUMN app_user.username", "用户名（唯一）"),
    ("COLUMN app_user.password_hash", "bcrypt 密码哈希"),
    ("COLUMN app_user.created_at", "注册时间"),
    # ---------- chat_session：会话 ----------
    ("TABLE chat_session", "对话会话；id 同时作为 LangGraph thread_id"),
    ("COLUMN chat_session.id", "会话 id(uuid)"),
    ("COLUMN chat_session.user_id", "所属用户(外键 app_user)"),
    ("COLUMN chat_session.title", "会话标题（首条问题自动命名）"),
    ("COLUMN chat_session.db_id", "本会话的目标数据库"),
    ("COLUMN chat_session.created_at", "创建时间"),
    ("COLUMN chat_session.updated_at", "最后活动时间（用于列表排序）"),
    # ---------- chat_message：消息 ----------
    ("TABLE chat_message", "会话内的消息，是多轮历史与 UI 展示的真相来源"),
    ("COLUMN chat_message.id", "主键"),
    ("COLUMN chat_message.session_id", "所属会话(外键 chat_session)"),
    ("COLUMN chat_message.role", "角色：user | assistant"),
    ("COLUMN chat_message.content", "消息文本（assistant 为自然语言回答）"),
    ("COLUMN chat_message.sql", "assistant 消息附带的生成 SQL"),
    ("COLUMN chat_message.result", "assistant 消息附带的执行结果(JSON：columns/rows/row_count)"),
    ("COLUMN chat_message.created_at", "创建时间"),
]


def upgrade() -> None:
    for obj, comment in _COMMENTS:
        safe = comment.replace("'", "''")
        op.execute(f"COMMENT ON {obj} IS '{safe}'")


def downgrade() -> None:
    for obj, _ in _COMMENTS:
        op.execute(f"COMMENT ON {obj} IS NULL")
