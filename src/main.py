"""FastAPI application entrypoint."""

# 应用生命周期集中管理数据库、MCP、检查点与长期记忆资源，避免请求内重复创建连接。

import asyncio
import logging
import sys
import time
import uuid
from contextlib import asynccontextmanager

# psycopg3 的异步连接不兼容 Windows 默认 ProactorEventLoop；必须在 Uvicorn 创建事件循环前切换。
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.agent.agent_factory import create_agent_service
from src.agent.checkpointer import create_checkpointer_context
from src.api.router import router
from src.config.load_settings import load_settings
from src.config.settings import Settings
from src.core.errors import DomainError
from src.common.httpx_client import HttpxClient
from src.core.logging import configure_logging
from src.core.request_context import request_id_var
from src.core.startup_secrets import resolve_runtime_secrets
from src.database.engine import create_engine
from src.mcp.manager import McpClientManager
from src.services.memory_service import MemoryService

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, database_url: str | None = None) -> FastAPI:
    """Create an application with resources owned by its lifespan."""
    configured_settings = settings

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # 延迟到服务实际启动时读取 YAML，避免模块导入或测试依赖本机私密环境变量。
        runtime_settings = configured_settings or load_settings()
        configure_logging(runtime_settings)
        app.state.runtime_secrets = await resolve_runtime_secrets(runtime_settings)
        engine = create_async_engine(database_url, pool_pre_ping=True) if database_url else create_engine(runtime_settings)
        app.state.settings = runtime_settings
        app.state.ready = False
        app.state.engine = engine
        app.state.session_factory = async_sessionmaker(engine, expire_on_commit=False)
        app.state.mcp_manager = McpClientManager(runtime_settings)
        await app.state.mcp_manager.start()
        app.state.httpx_client = None
        if runtime_settings.tools.external_status_url is not None or runtime_settings.agent.token_auth is not None:
            app.state.httpx_client = HttpxClient(runtime_settings.tools.root_ca_path)
            logger.info("httpx_client_initialized root_ca_path=%s", runtime_settings.tools.root_ca_path)
        logger.info("application_resources_initializing env=%s", runtime_settings.app_env)
        if database_url is None:
            async with create_checkpointer_context(runtime_settings) as checkpointer:
                await checkpointer.setup()
                app.state.checkpointer = checkpointer
                from langgraph.store.postgres import AsyncPostgresStore

                async with AsyncPostgresStore.from_conn_string(runtime_settings.psycopg_url) as memory_store:
                    await memory_store.setup()
                    app.state.memory_service = MemoryService(memory_store)
                    app.state.agent_service = create_agent_service(
                        runtime_settings,
                        app.state.mcp_manager,
                        app.state.memory_service,
                        app.state.runtime_secrets,
                        app.state.httpx_client,
                        checkpointer,
                        app.state.session_factory,
                    )
                    logger.info("application_resources_ready persistence=postgres")
                    app.state.ready = True
                    try:
                        yield
                    finally:
                        app.state.ready = False
                        if app.state.httpx_client is not None:
                            await app.state.httpx_client.close()
                        await app.state.mcp_manager.close()
                        await engine.dispose()
        else:
            from langgraph.store.memory import InMemoryStore

            app.state.checkpointer = None
            app.state.memory_service = MemoryService(InMemoryStore())
            app.state.agent_service = create_agent_service(
                runtime_settings,
                app.state.mcp_manager,
                app.state.memory_service,
                app.state.runtime_secrets,
                app.state.httpx_client,
                session_factory=app.state.session_factory,
            )
            logger.info("application_resources_ready persistence=in_memory")
            app.state.ready = True
            try:
                yield
            finally:
                app.state.ready = False
                if app.state.httpx_client is not None:
                    await app.state.httpx_client.close()
                await app.state.mcp_manager.close()
                await engine.dispose()

    app = FastAPI(title="DeepAgent Platform MVP", lifespan=lifespan)
    app.include_router(router)

    @app.get("/health", include_in_schema=False)
    async def health(request: Request) -> JSONResponse:
        """返回资源是否已完成初始化；此探针接口不需要认证。"""
        if not request.app.state.ready:
            return JSONResponse(status_code=503, content={"status": "not_ready"})
        return JSONResponse(content={"status": "ok"})

    @app.exception_handler(DomainError)
    async def domain_error_handler(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code, content={"code": exc.code, "message": exc.message}
        )

    @app.middleware("http")
    async def request_logging(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            logger.info(
                "http_request method=%s path=%s status_code=%s duration_ms=%d",
                request.method,
                request.url.path,
                response.status_code,
                (time.perf_counter() - started) * 1000,
            )
            return response
        finally:
            request_id_var.reset(token)

    return app


app = create_app()


def start_server() -> None:
    """以模块方式启动本地 Uvicorn 服务。"""
    # 使用 import string 让 Uvicorn 能正确管理应用生命周期和可选 reload。
    import uvicorn

    logger.info("server_starting host=0.0.0.0 port=8000")
    uvicorn.run("src.main:app", host="0.0.0.0", port=8000)


if __name__ == "__main__":
    start_server()
