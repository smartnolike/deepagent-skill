"""Staff-isolated long-term memory operations."""

# 长期记忆只接受显式 API 写入，并使用 staff namespace 防止跨员工读取。

import logging
from langgraph.store.base import BaseStore

logger = logging.getLogger(__name__)


class MemoryService:
    """Persist explicit, structured staff memories in the LangGraph Store."""

    def __init__(self, store: BaseStore) -> None:
        self._store = store

    async def put(self, staff_id: str, key: str, value: dict[str, str]) -> dict[str, object]:
        """Create or replace one explicitly supplied staff memory."""
        await self._store.aput(self._namespace(staff_id), key, value, index=False)
        logger.info("memory_saved staff_id=%s memory_key=%s", staff_id, key)
        return {"key": key, "value": value}

    async def list(self, staff_id: str) -> list[dict[str, object]]:
        """Return the staff's stored memories without crossing namespaces."""
        items = await self._store.asearch(self._namespace(staff_id), limit=100)
        logger.info("memory_listed staff_id=%s count=%s", staff_id, len(items))
        return [{"key": item.key, "value": item.value} for item in items]

    async def get(self, staff_id: str, key: str) -> dict[str, str] | None:
        """Load one exact staff-scoped memory key without exposing unrelated entries."""
        item = await self._store.aget(self._namespace(staff_id), key)
        if item is None:
            logger.info("memory_not_found staff_id=%s memory_key=%s", staff_id, key)
            return None
        value = item.value
        if not isinstance(value, dict) or not all(isinstance(item_value, str) for item_value in value.values()):
            logger.warning("memory_ignored_invalid_value staff_id=%s memory_key=%s", staff_id, key)
            return None
        logger.info("memory_loaded staff_id=%s memory_key=%s", staff_id, key)
        return dict(value)

    async def delete(self, staff_id: str, key: str) -> None:
        """Delete one memory in the current staff namespace."""
        await self._store.adelete(self._namespace(staff_id), key)
        logger.info("memory_deleted staff_id=%s memory_key=%s", staff_id, key)

    def _namespace(self, staff_id: str) -> tuple[str, str, str]:
        return ("staff", staff_id, "memory")
