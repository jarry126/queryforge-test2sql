"""Alembic 环境（在线模式，使用应用配置 DSN）。"""

from __future__ import annotations

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import settings

config = context.config
# 用应用配置覆盖连接串（psycopg3 驱动）
config.set_main_option("sqlalchemy.url", settings.postgres_dsn.replace("postgresql://", "postgresql+psycopg://"))

target_metadata = None


def run_migrations_offline() -> None:
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
