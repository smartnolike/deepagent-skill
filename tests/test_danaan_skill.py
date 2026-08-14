"""Danaan Skill memory-confirmation instruction regression tests."""

# 这类行为由 DeepAgent 读取 SKILL.md 决定；测试固定关键规则，防止回归为首次命中记忆就打开表单。

from pathlib import Path


def test_saved_danaan_context_requires_natural_language_confirmation_before_form() -> None:
    """完整记忆先经自然语言确认，拒绝后才允许请求表单。"""
    skill_path = Path(__file__).parents[1] / "skill-packages" / "danaan-cloud-resource" / "SKILL.md"
    content = skill_path.read_text(encoding="utf-8")

    assert "不得调用 `request_user_form`，也不得触发任何表单 SSE 事件" in content
    assert "这是一个普通 Agent 回复，必须等待用户的下一条自然语言消息" in content
    assert "用户明确否定、要求重新选择或要求修改基础资料后，才调用" in content
    assert "prefilled_values = danaan_base_context" in content
