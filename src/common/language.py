"""响应语言判定工具。"""

# 语言判定不依赖模型：用户输入中只要出现中文字符，就以中文作为本轮主语言。

import re
from typing import Literal

ResponseLanguage = Literal["zh-CN", "en"]

_HAN_CHARACTER = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]")


def resolve_response_language(text: str | None, accept_language: str | None = None) -> ResponseLanguage:
    """根据用户文本优先、Accept-Language 兜底规则确定响应语言。"""
    if text and _HAN_CHARACTER.search(text):
        return "zh-CN"
    if text:
        return "en"
    if accept_language and accept_language.lower().startswith("en"):
        return "en"
    return "zh-CN"
