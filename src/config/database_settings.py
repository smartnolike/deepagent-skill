"""Database YAML configuration model."""

# 业务数据库和 LangGraph PostgreSQL 组件共用此连接信息，但使用不同驱动。

from pydantic import BaseModel, Field


class DatabaseSettings(BaseModel):
    """Database connectivity settings shared by SQLAlchemy and psycopg."""

    host: str
    port: int = 5432
    name: str
    user: str
    password: str | None = None
    options: dict[str, str] = Field(default_factory=dict)
