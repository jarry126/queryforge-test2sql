"""为 chat_message 增加问答轮次 id

Revision ID: 0005_chat_message_turn_id
Revises: 0004_comments
Create Date: 2026-06-25
"""

from __future__ import annotations

from alembic import op

revision = "0005_chat_message_turn_id"
down_revision = "0004_comments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE chat_message ADD COLUMN IF NOT EXISTS turn_id TEXT")
    op.execute("CREATE INDEX IF NOT EXISTS idx_chat_message_turn ON chat_message (session_id, turn_id, id)")
    op.execute("COMMENT ON COLUMN chat_message.turn_id IS '问答轮次 id；同一轮 user 问题与 assistant 回答共享'")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_chat_message_turn")
    op.execute("ALTER TABLE chat_message DROP COLUMN IF EXISTS turn_id")
