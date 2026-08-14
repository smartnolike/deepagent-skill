"""Danaan 外部表 SQLAlchemy Declarative Base。"""

# 独立 metadata 确保 Alembic 不会把 Danaan 表纳入本项目的 schema 管理。

from sqlalchemy.orm import DeclarativeBase


class DanaanReadBase(DeclarativeBase):
    """Danaan 只读 Model 的独立 declarative base。"""
