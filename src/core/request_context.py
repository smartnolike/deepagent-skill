"""Request correlation context."""

# ContextVar 让同一异步请求链路中的日志自动关联 request_id。

from contextvars import ContextVar


request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
