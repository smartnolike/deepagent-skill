"""LangChain Tool registration for namespaced MCP capabilities."""

# 将 MCP 工具映射为 server_id__tool_name，避免多个 Server 的工具同名。

import json
from copy import deepcopy
from typing import Annotated
from typing import Any

from langchain_core.tools import InjectedToolArg, StructuredTool
from langgraph.prebuilt import ToolRuntime

from src.mcp.manager import McpClientManager


class McpToolRegistry:
    """Expose each configured MCP allowlisted tool to the root DeepAgent."""

    def __init__(self, manager: McpClientManager) -> None:
        self._manager = manager

    def build(self) -> list[StructuredTool]:
        """Create namespaced Tools using the MCP Server's real input schemas."""
        tools: list[StructuredTool] = []
        for server_id, definitions in self._manager.tool_definitions.items():
            for definition in definitions:
                qualified_name = f"{server_id}__{definition.name}"
                server = self._manager.server_settings[server_id]
                context_bindings = server.context_argument_bindings.get(definition.name, {})
                fixed_arguments = server.fixed_arguments.get(definition.name, {})
                tools.append(
                    StructuredTool(
                        coroutine=self._tool_callable(qualified_name, context_bindings, fixed_arguments),
                        name=qualified_name,
                        description=definition.description,
                        # 系统字段不发给模型；执行时才从可信 runtime 注入。
                        args_schema=_without_system_argument_paths(
                            definition.input_schema, set(context_bindings) | set(fixed_arguments)
                        ),
                    )
                )
        return tools

    def _tool_callable(
        self,
        qualified_name: str,
        context_bindings: dict[str, str],
        fixed_arguments: dict[str, str],
    ):
        async def invoke(
            runtime: Annotated[ToolRuntime, InjectedToolArg()] | None = None, **arguments: Any
        ) -> str:
            final_arguments = deepcopy(arguments)
            if context_bindings and runtime is None:
                raise RuntimeError("MCP tool requires an injected runtime context")
            for path, context_key in context_bindings.items():
                if runtime is None:
                    raise RuntimeError("MCP tool requires an injected runtime context")
                _set_argument_path(final_arguments, path, runtime.context[context_key])
            for path, value in fixed_arguments.items():
                _set_argument_path(final_arguments, path, value)
            result = await self._manager.call_tool(qualified_name, final_arguments)
            return json.dumps(result, ensure_ascii=False)

        return invoke


def _without_system_argument_paths(input_schema: dict[str, Any], paths: set[str]) -> dict[str, Any]:
    """Return a model-visible schema that excludes server-injected dotted argument paths."""
    schema = deepcopy(input_schema)
    for path in paths:
        _remove_schema_path(schema, path.split("."))
    return schema


def _remove_schema_path(schema: dict[str, Any], path: list[str]) -> None:
    """Remove one nested property and its required marker from a JSON Schema object."""
    if not path:
        return
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return
    field = path[0]
    if len(path) == 1:
        properties.pop(field, None)
        required = schema.get("required")
        if isinstance(required, list):
            schema["required"] = [item for item in required if item != field]
        return
    nested_schema = properties.get(field)
    if isinstance(nested_schema, dict):
        _remove_schema_path(nested_schema, path[1:])


def _set_argument_path(arguments: dict[str, Any], path: str, value: object) -> None:
    """Set a dotted argument path, replacing any model-supplied value at that path."""
    current = arguments
    parts = path.split(".")
    for part in parts[:-1]:
        nested = current.get(part)
        if not isinstance(nested, dict):
            nested = {}
            current[part] = nested
        current = nested
    current[parts[-1]] = value
