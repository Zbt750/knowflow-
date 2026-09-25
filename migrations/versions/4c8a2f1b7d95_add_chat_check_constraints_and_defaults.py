"""补齐 chat 表的 CHECK 约束与列默认值。

为什么要单独一个迁移：
`9b7f1d3e2c6a` 建表时漏掉了模型里声明的三个 CHECK 约束，也没有给列写
`server_default`。两者都是真实缺口：

1. **CHECK 约束缺失**：数据库层拦不住非法取值。契约要求 `mode` 只能是
   `builtin`/`user`、`status` 只能是四种生成状态 —— 没有约束时，
   一条写错 mode 的历史会话会**静默跨库检索**（用错误的 source_types 过滤），
   属于「不报错但结果错」的缺陷。
2. **server_default 缺失**：模型上的 `default=` 只作用于 ORM 插入；
   直接 SQL 或不带该字段的插入会因 NOT NULL 直接失败。

实现上刻意使用**纯 SQL** 而不是 `op.create_check_constraint`：
本项目 `Base` 配置了命名约定 `ck_%(table_name)s_%(constraint_name)s`，
而 Alembic 生成 DDL 时也会套用这套约定 —— 于是「传进去的名字」与
「落库的名字」很容易错位，写错时会出现**重复前缀**或**重复约束**，
连 downgrade 都会失败（本项目实际踩过）。纯 SQL 让落库名字完全确定。

注意 `alembic check` 检测不到这个差异 —— 它默认不比较 CHECK 约束，
所以「迁移与模型一致」必须靠**真实约束存在性测试**验证，不能靠 autogenerate。

Revision ID: 4c8a2f1b7d95
Revises: 9b7f1d3e2c6a
"""

from alembic import op

revision = "4c8a2f1b7d95"
down_revision = "9b7f1d3e2c6a"
branch_labels = None
depends_on = None

# 约束名必须与 Base 命名约定算出的结果完全一致：ck_<table>_<constraint_name>。
# 模型里声明的 constraint_name 依次是
# chat_session_mode_valid / chat_message_role_valid / chat_message_status_valid。
MODE_CHECK = "ck_chat_sessions_chat_session_mode_valid"
ROLE_CHECK = "ck_chat_messages_chat_message_role_valid"
STATUS_CHECK = "ck_chat_messages_chat_message_status_valid"


def _drop_all_check_constraints(table: str) -> None:
    """删掉某张表上的**全部** CHECK 约束。

    为什么直接全删：本迁移的目标是「让约束集合与模型一致」。
    历史版本可能留下不按约定命名的等价约束（本项目实际出现过），
    逐个判断名字容易漏。chat 两张表只有下面要重建的这几条约束，
    全删再按约定重建，结果确定，而且可以重复执行。
    """
    op.execute(
        f"""
        DO $$
        DECLARE r record;
        BEGIN
            FOR r IN
                SELECT conname FROM pg_constraint
                WHERE conrelid = '{table}'::regclass AND contype = 'c'
            LOOP
                EXECUTE format('ALTER TABLE {table} DROP CONSTRAINT %I', r.conname);
            END LOOP;
        END $$;
        """
    )


def upgrade() -> None:
    # 1) 清掉所有历史遗留 CHECK（含早期写错名字的那些），再按约定重建。
    _drop_all_check_constraints("chat_sessions")
    _drop_all_check_constraints("chat_messages")

    op.execute(
        f"ALTER TABLE chat_sessions ADD CONSTRAINT {MODE_CHECK} "
        "CHECK (mode IN ('builtin', 'user'))"
    )
    op.execute(
        f"ALTER TABLE chat_messages ADD CONSTRAINT {ROLE_CHECK} "
        "CHECK (role IN ('user', 'assistant', 'system'))"
    )
    op.execute(
        f"ALTER TABLE chat_messages ADD CONSTRAINT {STATUS_CHECK} "
        "CHECK (status IN ('completed', 'generating', 'cancelled', 'failed'))"
    )

    # 2) 列默认值：与模型声明一致，让非 ORM 写入也不会因为漏字段而失败。
    op.execute("ALTER TABLE chat_sessions ALTER COLUMN title SET DEFAULT '新对话'")
    op.execute("ALTER TABLE chat_sessions ALTER COLUMN mode SET DEFAULT 'builtin'")
    op.execute("ALTER TABLE chat_messages ALTER COLUMN content SET DEFAULT ''")
    op.execute("ALTER TABLE chat_messages ALTER COLUMN status SET DEFAULT 'generating'")
    op.execute("ALTER TABLE chat_messages ALTER COLUMN metadata SET DEFAULT '{}'::json")


def downgrade() -> None:
    """回到 9b7f1d3e2c6a 建表后的样子：没有 CHECK，也没有列默认值。"""
    op.execute("ALTER TABLE chat_messages ALTER COLUMN metadata DROP DEFAULT")
    op.execute("ALTER TABLE chat_messages ALTER COLUMN status DROP DEFAULT")
    op.execute("ALTER TABLE chat_messages ALTER COLUMN content DROP DEFAULT")
    op.execute("ALTER TABLE chat_sessions ALTER COLUMN mode DROP DEFAULT")
    op.execute("ALTER TABLE chat_sessions ALTER COLUMN title DROP DEFAULT")

    _drop_all_check_constraints("chat_messages")
    _drop_all_check_constraints("chat_sessions")
