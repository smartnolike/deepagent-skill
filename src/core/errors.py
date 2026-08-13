"""Domain errors mapped to stable API error payloads."""

# 领域错误统一转换为稳定 code/message，避免把内部异常直接返回给客户端。


class DomainError(Exception):
    """Expected application error with an HTTP status and stable code."""

    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
