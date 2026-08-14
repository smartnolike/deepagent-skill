"""最小自定义 Tool 示例。"""

# 这个 Tool 不依赖数据库、HTTP 或 MCP，适合作为新增应用内 Tool 的参考模板。

from langchain_core.tools import tool


@tool
async def echo_text(text: str) -> str:
    """原样返回输入文本，用于测试 Agent 的自定义 Tool 调用。"""
    return text
