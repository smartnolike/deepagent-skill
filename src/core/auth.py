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


async def require_quota_admin_token(
    request: Request, x_quota_admin_token: str | None = Header(default=None)
) -> None:
    """Protect quota administration separately from the browser-facing API token."""
    configured = request.app.state.settings.quota_admin_token
    if configured is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
    if not x_quota_admin_token or not secrets.compare_digest(
        x_quota_admin_token, configured.get_secret_value()
    ):
        logger.warning("quota_admin_auth_failed")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
