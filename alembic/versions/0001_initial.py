"""初始化：扩展 + RAG 表（schema 文档 / few-shot / 业务文档块）

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-23
"""

from __future__ import annotations

from alembic import op

from app.core.config import settings

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

DIM = settings.EMBEDDING_DIM


def upgrade() -> None:
    # 1) 扩展
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_jieba")

    # 2) schema 文档：每行一段可检索的 schema 描述（库 / 表 / 列粒度）
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS schema_doc (
            id          BIGSERIAL PRIMARY KEY,
            db_id       TEXT NOT NULL,
            doc_type    TEXT NOT NULL,            -- table | column | db
            table_name  TEXT,
            content     TEXT NOT NULL,            -- 用于检索与喂给 LLM 的文本
            embedding   vector({DIM}),
            tsv         tsvector,
            metadata    JSONB DEFAULT '{{}}'::jsonb,
            created_at  TIMESTAMPTZ DEFAULT now()
        )
        """
    )
    # 3) few-shot：相似 NL->SQL 示例库
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS fewshot_example (
            id         BIGSERIAL PRIMARY KEY,
            db_id      TEXT NOT NULL,
            question   TEXT NOT NULL,
            sql        TEXT NOT NULL,
            embedding  vector({DIM}),
            tsv        tsvector,
            created_at TIMESTAMPTZ DEFAULT now()
        )
        """
    )
    # 4) 业务文档块（对应手绘上传链路：table/text/image/summary）
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS rag_chunk (
            id         BIGSERIAL PRIMARY KEY,
            doc_id     TEXT NOT NULL,
            chunk_type TEXT NOT NULL,             -- table | text | image | summary
            page       INT,
            content    TEXT NOT NULL,
            embedding  vector({DIM}),
            tsv        tsvector,
            metadata   JSONB DEFAULT '{{}}'::jsonb,  -- summary 在此存 chunk_id 集合
            created_at TIMESTAMPTZ DEFAULT now()
        )
        """
    )

    # 5) 索引：向量用 HNSW（cosine），全文用 GIN
    for tbl in ("schema_doc", "fewshot_example", "rag_chunk"):
        op.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{tbl}_embedding ON {tbl} "
            f"USING hnsw (embedding vector_cosine_ops)"
        )
        op.execute(f"CREATE INDEX IF NOT EXISTS idx_{tbl}_tsv ON {tbl} USING gin (tsv)")

    op.execute("CREATE INDEX IF NOT EXISTS idx_schema_doc_db ON schema_doc (db_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_fewshot_db ON fewshot_example (db_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS rag_chunk")
    op.execute("DROP TABLE IF EXISTS fewshot_example")
    op.execute("DROP TABLE IF EXISTS schema_doc")
