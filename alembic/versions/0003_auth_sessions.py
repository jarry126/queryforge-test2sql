"""鉴权与会话：users / sessions / messages

Revision ID: 0003_auth_sessions
Revises: 0002_query_cache
Create Date: 2026-06-24
"""

from __future__ import annotations

from alembic import op

revision = "0003_auth_sessions"
down_revision = "0002_query_cache"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS app_user (
            id            BIGSERIAL PRIMARY KEY,
            username      TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at    TIMESTAMPTZ DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_session (
            id         TEXT PRIMARY KEY,                 -- uuid，同时作为 LangGraph thread_id
            user_id    BIGINT NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
            title      TEXT NOT NULL DEFAULT '新会话',
            db_id      TEXT NOT NULL,                    -- 该会话的目标数据库
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_message (
            id         BIGSERIAL PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES chat_session(id) ON DELETE CASCADE,
            role       TEXT NOT NULL,                    -- user | assistant
            content    TEXT NOT NULL,
            sql        TEXT,                             -- assistant 消息附带生成的 SQL
            result     JSONB,                            -- assistant 消息附带执行结果
            created_at TIMESTAMPTZ DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_chat_session_user ON chat_session (user_id, updated_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_chat_message_session ON chat_message (session_id, id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS chat_message")
    op.execute("DROP TABLE IF EXISTS chat_session")
    op.execute("DROP TABLE IF EXISTS app_user")
