"""响应语言判定工具。"""

# 语言判定不依赖模型：用户输入中只要出现中文字符，就以中文作为本轮主语言。

import re
from typing import Literal

ResponseLanguage = Literal["zh-CN", "en"]

_HAN_CHARACTER = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]")
_FIELD_VALUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+=-]*$")


def resolve_response_language(
    text: str | None,
    accept_language: str | None = None,
    previous_language: ResponseLanguage | None = None,
) -> ResponseLanguage:
    """根据用户文本优先、上下文继承和 Accept-Language 兜底确定响应语言。"""
    if text and _HAN_CHARACTER.search(text):
        return "zh-CN"
    if _is_field_value(text) and previous_language is not None:
        return previous_language
    if text:
        return "en"
    if accept_language and accept_language.lower().startswith("en"):
        return "en"
    return "zh-CN"


def _is_field_value(text: str | None) -> bool:
    """Return whether text looks like a technical value rather than an English sentence."""
    if not text or not _FIELD_VALUE.fullmatch(text):
        return False
    # Separators or digits distinguish IDs and resource names from replies such as
    # "yes" and "continue", which should still select English.
    return any(character.isdigit() or character in "._:/@+=-" for character in text)
