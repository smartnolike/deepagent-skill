"""Danaan 资源模板 Agent Tool。"""

# 每次 Tool 调用创建并关闭独立数据库 Session，绝不将 request Session 保存到 Agent 单例。

import json

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.repositories.danaan_template_repository import DanaanTemplateRepository


async def get_danaan_resource_template(
    session_factory: async_sessionmaker[AsyncSession], resource_name: str
) -> str:
    """读取资源名称对应的最新 Danaan resourceContent 模板。"""
    async with session_factory() as session:
        template = await DanaanTemplateRepository(session).get_latest_template_content(resource_name)
    return json.dumps(
        {"found": template is not None, "resource_name": resource_name, "resource_content": template},
        ensure_ascii=False,
    )
