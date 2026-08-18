"""使用指定根证书访问外部 API 的专用异步 HTTP 客户端。"""

# 所有外部 HTTP 请求共用一个 AsyncClient，复用连接池并强制使用 build/root.cer 校验服务端证书。

import logging
import time
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)


class HttpxClient:
    """受控的外部 API HTTP 客户端。"""

    def __init__(self, root_ca_path: Path, transport: httpx.AsyncBaseTransport | None = None) -> None:
        resolved_path = root_ca_path.resolve()
        if not resolved_path.is_file() or resolved_path.stat().st_size == 0:
            raise RuntimeError(f"External HTTP root certificate is missing or empty: {resolved_path}")
        self._client = httpx.AsyncClient(
            verify=str(resolved_path),
            timeout=httpx.Timeout(10.0),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )

    async def get_json(self, url: str) -> dict[str, object]:
        """执行受控 GET 请求并只返回 JSON object。"""
        started = time.perf_counter()
        try:
            response = await self._client.get(url)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("External API response must be a JSON object")
            logger.info(
                "external_http_completed",
                extra={
                    "fields": {
                        "host": response.url.host,
                        "status_code": response.status_code,
                        "duration_ms": int((time.perf_counter() - started) * 1000),
                    }
                },
            )
            return payload
        except Exception as exc:
            logger.exception(
                "external_http_failed",
                extra={
                    "fields": {
                        "host": httpx.URL(url).host,
                        "error_type": type(exc).__name__,
                        "duration_ms": int((time.perf_counter() - started) * 1000),
                    }
                },
            )
            raise

    @property
    def async_client(self) -> httpx.AsyncClient:
        """Expose the application-owned client for compatible async SDKs."""
        return self._client

    async def post_json(
        self, url: str, payload: dict[str, object], timeout_seconds: float
    ) -> dict[str, object]:
        """执行 JSON POST；日志不记录请求 payload、header 或响应正文。"""
        started = time.perf_counter()
        try:
            response = await self._client.post(url, json=payload, timeout=timeout_seconds)
            response.raise_for_status()
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError("External API response must be a JSON object")
            logger.info(
                "external_http_completed",
                extra={
                    "fields": {
                        "host": response.url.host,
                        "status_code": response.status_code,
                        "duration_ms": int((time.perf_counter() - started) * 1000),
                    }
                },
            )
            return result
        except Exception as exc:
            logger.exception(
                "external_http_failed",
                extra={
                    "fields": {
                        "host": httpx.URL(url).host,
                        "error_type": type(exc).__name__,
                        "duration_ms": int((time.perf_counter() - started) * 1000),
                    }
                },
            )
            raise

    async def close(self) -> None:
        """在应用关闭时释放 HTTP 连接池。"""
        await self._client.aclose()
