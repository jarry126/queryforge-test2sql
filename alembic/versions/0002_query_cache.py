"""语义近似缓存表 query_cache

Revision ID: 0002_query_cache
Revises: 0001_initial
Create Date: 2026-06-23
"""

from __future__ import annotations

from alembic import op

from app.core.config import settings

revision = "0002_query_cache"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

DIM = settings.EMBEDDING_DIM


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS query_cache (
            id         BIGSERIAL PRIMARY KEY,
            db_id      TEXT NOT NULL,
            question   TEXT NOT NULL,
            embedding  vector({DIM}) NOT NULL,
            response   JSONB NOT NULL,
            created_at TIMESTAMPTZ DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_query_cache_embedding ON query_cache "
        "USING hnsw (embedding vector_cosine_ops)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_query_cache_db ON query_cache (db_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_query_cache_created ON query_cache (created_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS query_cache")
