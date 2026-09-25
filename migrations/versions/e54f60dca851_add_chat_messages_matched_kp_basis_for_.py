"""add chat_messages.matched_kp_basis for attribution

Revision ID: e54f60dca851
Revises: b58f3c7e91a4
Create Date: 2026-09-19 22:04:25.187021

给 chat_messages 增加 matched_kp 的归因依据列。

为什么要存依据而不只存 matched_kp_id：
归因结果决定「推荐哪些追练题」，用户有权知道凭什么归到这个知识点。
只存结论时，前端无法解释、事后也无法排查错归因 ——
重新跑一次检索并不等于当时的检索（资料可能已重建索引）。

存量消息没有当时的依据可回溯，统一补空对象 `{}`，
读取端按「无依据」处理（与拒答、无知识点过阈值的情况同构）。
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'e54f60dca851'
down_revision: str | None = 'b58f3c7e91a4'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # server_default 必须与 NOT NULL 一起给：表里已有历史消息，
    # 分两步（先加可空列再置 NOT NULL）也行，但这里一句更短且同样安全。
    op.add_column(
        "chat_messages",
        sa.Column(
            "matched_kp_basis",
            sa.JSON(),
            server_default=sa.text("'{}'::json"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("chat_messages", "matched_kp_basis")
