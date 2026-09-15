"""Danaan cloud_resource_template_info 外部表映射。"""

# 字段来自 Danaan 表定义；本 Model 只用于 SELECT，严禁由本应用写入或迁移。

from datetime import datetime

from sqlalchemy import DateTime, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.models.danaan.base import DanaanReadBase


class CloudResourceTemplateInfo(DanaanReadBase):
    """Danaan 云资源模板的只读 SQLAlchemy Model。"""

    __tablename__ = "cloud_resource_template_info"
    __table_args__ = {"info": {"read_only": True}}

    res_template_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cloud_resource_name: Mapped[str] = mapped_column(Text, nullable=False)
    template_content: Mapped[str] = mapped_column(Text, nullable=False)
    editable_fields: Mapped[str | None] = mapped_column(Text, nullable=True)
    update_editable_fields: Mapped[str | None] = mapped_column(Text, nullable=True)
    json_schema: Mapped[str | None] = mapped_column(Text, nullable=True)
    req_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delete_flag: Mapped[int | None] = mapped_column(Integer, nullable=True)
    template_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    template_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    module_name: Mapped[str | None] = mapped_column(Text, nullable=True)
