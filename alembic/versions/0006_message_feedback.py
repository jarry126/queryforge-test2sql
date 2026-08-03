"""问答反馈：点赞/点踩 + 可选说明

Revision ID: 0006_message_feedback
Revises: 0005_chat_message_turn_id
Create Date: 2026-08-03
"""

from __future__ import annotations

from alembic import op

revision = "0006_message_feedback"
down_revision = "0005_chat_message_turn_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS message_feedback (
            id            BIGSERIAL PRIMARY KEY,
            message_id    BIGINT NOT NULL REFERENCES chat_message(id) ON DELETE CASCADE,
            user_id       BIGINT NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
            session_id    TEXT NOT NULL REFERENCES chat_session(id) ON DELETE CASCADE,
            rating        TEXT NOT NULL CHECK (rating IN ('up', 'down')),
            comment       TEXT,
            question_text TEXT NOT NULL DEFAULT '',
            created_at    TIMESTAMPTZ DEFAULT now(),
            updated_at    TIMESTAMPTZ DEFAULT now(),
            UNIQUE (message_id, user_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_message_feedback_user "
        "ON message_feedback (user_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_message_feedback_session "
        "ON message_feedback (session_id, created_at DESC)"
    )
    op.execute("COMMENT ON TABLE message_feedback IS '用户对某次助手回答的点赞/点踩反馈'")
    op.execute("COMMENT ON COLUMN message_feedback.rating IS 'up=满意, down=不满意'")
    op.execute(
        "COMMENT ON COLUMN message_feedback.question_text IS "
        "'提交时快照的用户问题，便于排查与改进'"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS message_feedback")
