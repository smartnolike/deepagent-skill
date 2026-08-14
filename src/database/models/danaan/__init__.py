"""Danaan 外部只读 SQLAlchemy Model。"""

# 不从 database.models 顶层导入，避免 Alembic 将外部表纳入迁移。
