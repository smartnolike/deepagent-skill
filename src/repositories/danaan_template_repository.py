"""Danaan 云资源模板只读查询。"""

# 该表由 Danaan 管理，不属于本应用 ORM 或 Alembic migration 的所有权范围。

import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.danaan.cloud_resource_template_info import CloudResourceTemplateInfo

logger = logging.getLogger(__name__)


class DanaanTemplateRepository:
    """从 Danaan 模板表读取指定资源名称的最新 resourceContent 模板。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_latest_template_content(self, resource_name: str) -> dict[str, Any] | str | None:
        """按资源名称读取最新模板；空名称或未匹配模板均返回 ``None``。"""
        normalized_resource_name = resource_name.strip()
        if not normalized_resource_name:
            logger.warning("danaan_template_lookup_skipped reason=empty_resource_name")
            return None
        statement = (
            select(CloudResourceTemplateInfo.template_content)
            .where(CloudResourceTemplateInfo.cloud_resource_name == normalized_resource_name)
            .order_by(
                CloudResourceTemplateInfo.req_time.desc().nulls_last(),
                CloudResourceTemplateInfo.res_template_id.desc(),
            )
            .limit(1)
        )
        logger.info("danaan_template_lookup_started resource_name_length=%s", len(normalized_resource_name))
        content = await self._session.scalar(statement)
        if content is None:
            logger.info("danaan_template_lookup_completed found=false")
            return None
        logger.info("danaan_template_lookup_completed found=true")
        if isinstance(content, str):
            try:
                decoded = json.loads(content)
            except json.JSONDecodeError:
                return content
            if isinstance(decoded, dict):
                return decoded
        if isinstance(content, dict):
            return content
        raise ValueError("Danaan template_content must be a JSON object or text template")
