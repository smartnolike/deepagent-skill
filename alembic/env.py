"""Alembic environment using the YAML-selected database URL."""

# 迁移复用 AGENT_ENV 选中的 YAML 数据库连接，生产执行前必须确认目标环境。

from alembic import context
from sqlalchemy import engine_from_config, pool

from src.config.load_settings import load_settings
from src.database.base import Base
from src.database.models.agent import agent_run, conversation, message  # noqa: F401

config = context.config
# 项目安装的是 psycopg3；Alembic 的同步 Engine 必须显式选择 psycopg 方言，不能回退到 psycopg2。
config.set_main_option("sqlalchemy.url", load_settings().psycopg_url.replace("postgresql://", "postgresql+psycopg://", 1))
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(config.get_section(config.config_ini_section), prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
