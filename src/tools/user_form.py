"""让 Agent 请求前端展示结构化表单的通用 Tool。"""

# 该 Tool 由 Human-in-the-Loop 的 respond 决策拦截，正常流程下函数体不会执行。

from typing import Any

from langchain_core.tools import tool


@tool
async def request_user_form(
    form_name: str, title: str, fields: list[dict[str, Any]], prefilled_values: dict[str, Any]
) -> str:
    """请求用户在前端完成表单；仅传递展示定义，不校验或保存业务参数。"""
    _ = form_name, title, fields, prefilled_values
    return "The user form request must be handled by the client."
