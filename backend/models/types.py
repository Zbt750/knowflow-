from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import Uuid
from sqlalchemy.orm import Mapped, mapped_column


def uuid_pk() -> Mapped[UUID]:
    """所有业务表统一使用应用侧生成的 UUID 主键。"""
    # 应用侧生成（default=uuid4）而不依赖数据库扩展，测试与迁移都不需要额外 CREATE EXTENSION。
    return mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)