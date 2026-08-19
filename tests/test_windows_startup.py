"""Windows Uvicorn event-loop selection tests."""

# psycopg3 异步连接不兼容 ProactorEventLoop；启动器必须显式覆盖 Uvicorn 的默认选择。

import main


def test_windows_startup_passes_selector_loop_to_uvicorn(monkeypatch) -> None:
    """Windows 启动路径显式指定 SelectorEventLoop，而非只依赖全局 policy。"""
    received: dict[str, object] = {}

    def run(_: str, **kwargs: object) -> None:
        received.update(kwargs)

    monkeypatch.setattr(main.sys, "platform", "win32")
    monkeypatch.setattr("uvicorn.run", run)

    main.start_server()

    assert received["loop"] == "asyncio:SelectorEventLoop"
