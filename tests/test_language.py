"""响应语言规则测试。"""

# 只要用户消息出现中文字符，就必须优先选择中文；否则使用英文或请求头兜底。

from common.language import resolve_response_language


def test_chinese_character_forces_chinese_response() -> None:
    assert resolve_response_language("Can you 帮我 create a bucket?") == "zh-CN"


def test_english_message_uses_english_response() -> None:
    assert resolve_response_language("Please create a bucket") == "en"


def test_accept_language_is_used_when_no_user_text_exists() -> None:
    assert resolve_response_language(None, "en-US,en;q=0.9") == "en"
