"""把 chat_messages 的 seq 索引改为 (session_id, seq) 复合索引。

原因：上一版迁移给的 `ix_chat_messages_seq` 只索引 seq 一列，
而模型里没有对应声明（alembic check 会报「待删除的索引」）。

更重要的是它**选错了列**：实际的查询模式是
「按 session_id 过滤，再按 seq 排序」（取某会话的历史消息）。
只索引 seq 对这类查询没有帮助；`(session_id, seq)` 复合索引
既服务于过滤+排序，也天然覆盖了「同一会话内 seq 递增」的语义。

Revision ID: b58f3c7e91a4
Revises: 7d2e5a9c4b31
"""

from alembic import op

revision = "b58f3c7e91a4"
down_revision = "7d2e5a9c4b31"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_chat_messages_seq")
    # 旧的单列 session_id 索引变成冗余：复合索引 (session_id, seq) 的最左前缀
    # 已经覆盖「按会话过滤」，保留两个只会让写入多维护一份索引。
    op.execute("DROP INDEX IF EXISTS ix_chat_messages_session_id")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_chat_messages_session_id_seq "
        "ON chat_messages (session_id, seq)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_chat_messages_session_id_seq")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_chat_messages_session_id ON chat_messages (session_id)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_chat_messages_seq ON chat_messages (seq)")
