"""Danaan 资源模板 Agent Tool。"""

# 每次 Tool 调用创建并关闭独立数据库 Session，绝不将 request Session 保存到 Agent 单例。

import json
import logging
import time

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from repositories.danaan_template_repository import DanaanTemplateRepository

logger = logging.getLogger(__name__)


async def get_danaan_resource_template(
    session_factory: async_sessionmaker[AsyncSession], resource_name: str
) -> str:
    """读取资源名称对应的最新 Danaan resourceContent 模板。"""
    started = time.perf_counter()
    logger.info(
        "danaan_resource_template_requested",
        extra={"fields": {"resource_name_length": len(resource_name)}},
    )
    try:
        async with session_factory() as session:
            template = await DanaanTemplateRepository(session).get_latest_template_content(resource_name)
    except Exception as exc:
        logger.exception(
            "danaan_resource_template_failed",
            extra={
                "fields": {
                    "resource_name_length": len(resource_name),
                    "error_type": type(exc).__name__,
                    "duration_ms": int((time.perf_counter() - started) * 1000),
                }
            },
        )
        raise
    logger.info(
        "danaan_resource_template_completed",
        extra={
            "fields": {
                "resource_name_length": len(resource_name),
                "found": template is not None,
                "duration_ms": int((time.perf_counter() - started) * 1000),
            }
        },
    )
    return json.dumps(
        {"found": template is not None, "resource_name": resource_name, "resource_content": template},
        ensure_ascii=False,
    )
