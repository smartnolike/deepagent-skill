"""Static bearer-token authentication for the MVP."""

# 静态 Token 仅用于 MVP 访问控制；日志只记录鉴权结果，绝不记录请求头或 Token 值。

import secrets
import logging

from fastapi import Header, HTTPException, Request, status

logger = logging.getLogger(__name__)


async def require_api_token(
    request: Request, authorization: str | None = Header(default=None)
) -> None:
    """Require the configured static bearer token without logging it."""
    expected = request.app.state.settings.api_auth_token.get_secret_value()
    prefix = "Bearer "
    if not authorization or not authorization.startswith(prefix):
        logger.warning("api_auth_failed reason=missing_or_invalid_scheme")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    if not secrets.compare_digest(authorization[len(prefix) :], expected):
        logger.warning("api_auth_failed reason=token_mismatch")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
