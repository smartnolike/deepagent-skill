"""受控的 Skill 长期记忆读取 Tool。"""

# Tool 仅使用 runtime 中的 staff_id，模型不能传入或伪造其他员工身份。

import json
import logging
import time

from langchain.tools import ToolRuntime
from langchain_core.tools import StructuredTool

from agent.agent_context import AgentContext
from services.danaan_memory import DANAAN_BASE_CONTEXT_KEY
from services.memory_service import MemoryService

logger = logging.getLogger(__name__)

ALLOWED_SKILL_MEMORY_KEYS = frozenset({DANAAN_BASE_CONTEXT_KEY})


def create_get_skill_memory_tool(memory_service: MemoryService) -> StructuredTool:
    """创建只能读取白名单记忆 key 的运行时 Tool。"""

    async def get_skill_memory(key: str, runtime: ToolRuntime[AgentContext]) -> str:
        """Read one allowlisted memory value for the current staff member only."""
        if key not in ALLOWED_SKILL_MEMORY_KEYS:
            logger.warning("skill_memory_access_denied", extra={"fields": {"memory_key": key}})
            return json.dumps({"found": False, "key": key, "error": "memory key is not allowed"})
        staff_id = runtime.context["staff_id"]
        started = time.perf_counter()
        try:
            value = await memory_service.get(staff_id, key)
        except Exception as exc:
            logger.exception(
                "skill_memory_read_failed",
                extra={
                    "fields": {
                        "staff_id": staff_id,
                        "memory_key": key,
                        "error_type": type(exc).__name__,
                        "duration_ms": int((time.perf_counter() - started) * 1000),
                    }
                },
            )
            raise
        logger.info(
            "skill_memory_read",
            extra={
                "fields": {
                    "staff_id": staff_id,
                    "memory_key": key,
                    "found": value is not None,
                    "duration_ms": int((time.perf_counter() - started) * 1000),
                }
            },
        )
        return json.dumps({"found": value is not None, "key": key, "value": value}, ensure_ascii=False)

    return StructuredTool.from_function(
        coroutine=get_skill_memory,
        name="get_skill_memory",
        description="Read one approved Skill memory key for the current staff member. The staff identity is injected at runtime.",
    )
