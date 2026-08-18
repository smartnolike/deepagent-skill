"""Request correlation context."""

# ContextVar 让同一异步请求链路中的日志自动关联 request_id。

from contextlib import contextmanager
from contextvars import ContextVar, Token


request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


@contextmanager
def bind_request_id(request_id: str):
    """Bind a request ID again when an SSE generator outlives HTTP middleware scope."""
    token: Token[str] = request_id_var.set(request_id)
    try:
        yield
    finally:
        request_id_var.reset(token)
