"""Danaan 模板 Repository 测试。"""

# 测试 Repository 只验证参数化查询与 JSON 模板解析，不依赖外部 Danaan 表或 Cloud SQL。

from unittest.mock import AsyncMock, MagicMock

import pytest

from repositories.danaan_template_repository import DanaanTemplateRepository


@pytest.mark.asyncio
async def test_get_latest_template_uses_resource_name_and_decodes_json() -> None:
    session = MagicMock()
    session.scalar = AsyncMock(
        return_value='{"template-resource-name":{"tier":"db-custom-1-3840"}}'
    )

    template = await DanaanTemplateRepository(session).get_latest_template_content(" Cloud SQL ")

    assert template == {"template-resource-name": {"tier": "db-custom-1-3840"}}
    statement = session.scalar.await_args.args[0]
    assert "public.cloud_resource_template_info" in str(statement)
    assert statement.compile().params == {"cloud_resource_name_1": "Cloud SQL", "param_1": 1}


@pytest.mark.asyncio
async def test_empty_resource_name_skips_database_query() -> None:
    session = MagicMock()
    session.scalar = AsyncMock()

    assert await DanaanTemplateRepository(session).get_latest_template_content("   ") is None
    session.scalar.assert_not_awaited()
