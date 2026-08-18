"""Minimal Agent test double injected only by API tests."""

from collections.abc import AsyncIterator
from typing import Any


class FakeAgentService:
    """Provide deterministic SSE events without putting fallback behavior in production code."""

    async def reply(self, *_: Any) -> AsyncIterator[tuple[str, dict[str, str]]]:
        """Return one stable assistant token."""
        yield "token", {"content": "Test agent response."}

    async def resume(self, *_: Any, **__: Any) -> AsyncIterator[tuple[str, dict[str, str]]]:
        """Return one stable confirmation token."""
        yield "token", {"content": "Test tool confirmation response."}
