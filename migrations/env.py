from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# 先 import 模型包，再读取 metadata；否则 autogenerate 看不到新表。
from backend.config import get_settings
from backend.models import import_models
from backend.models.base import Base

# Alembic 读取 alembic.ini 的日志配置；不在这里记录 DATABASE_URL。
config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

import_models()
target_metadata = Base.metadata


def get_database_url() -> str:
    """返回当前活动数据库 URL；APP_ENV=test 时只能返回 TEST_DATABASE_URL。"""
    # Alembic 与 FastAPI lifespan 共用 Settings.active_database_url，迁移不会悄悄写到开发库。
    return str(get_settings().active_database_url)


def run_migrations_offline() -> None:
    """离线模式只生成 SQL，不连接 PostgreSQL。"""
    # 离线路径没有连接对象，只把 SQL 打印出来；语句本身不在这里执行。
    context.configure(
        url=get_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,  # 参数内联成字面量，生成的 SQL 可直接阅读和执行。
        dialect_opts={"paramstyle": "named"},
        compare_type=True,  # 同时比较列类型，避免只改类型时漏生成迁移。
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式创建临时 migration 连接并执行 upgrade/downgrade。"""
    section = config.get_section(config.config_ini_section, {})
    # 不依赖 alembic.ini 中的 URL；始终使用 .env 或测试环境变量。
    section["sqlalchemy.url"] = get_database_url()
    # NullPool：迁移命令一结束就断开连接，不与应用运行时的连接池互相占用。
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        # 整条 migration 包在一个事务里；中途失败整体回滚，不留半成品表。
        with context.begin_transaction():
            context.run_migrations()


# 由 alembic 的调用方式决定路径：带 --sql 走离线，其余走在线。
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()