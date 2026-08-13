"""SQLAlchemy declarative base."""

# 只包含业务 ORM 模型；LangGraph 内部表不继承该 Base。

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for application-owned ORM models."""
