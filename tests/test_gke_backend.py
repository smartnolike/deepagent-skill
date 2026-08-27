from types import SimpleNamespace

import pytest

from sandbox.gke_backend import GkeSandboxBackend


class FakeFiles:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}

    def write(self, path: str, content: bytes) -> None:
        self.values[path] = content

    def read(self, path: str) -> bytes:
        return self.values[path]


class FakeCommands:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def run(self, command: str, timeout: int):
        self.calls.append((command, timeout))
        return SimpleNamespace(stdout="created\n", stderr="warning\n", exit_code=0)


def backend() -> tuple[GkeSandboxBackend, SimpleNamespace]:
    sandbox = SimpleNamespace(claim_name="claim-1", files=FakeFiles(), commands=FakeCommands())
    return GkeSandboxBackend(sandbox, default_timeout=120), sandbox


def test_execute_uses_default_timeout_and_combines_output() -> None:
    adapter, sandbox = backend()

    result = adapter.execute("python script.py")

    assert adapter.id == "claim-1"
    assert sandbox.commands.calls == [("python script.py", 120)]
    assert result.output == "created\nwarning\n"
    assert result.exit_code == 0


@pytest.mark.asyncio
async def test_async_execute_accepts_override_timeout() -> None:
    adapter, sandbox = backend()

    result = await adapter.aexecute("pwd", timeout=5)

    assert result.exit_code == 0
    assert sandbox.commands.calls == [("pwd", 5)]


def test_upload_and_download_files_are_provider_neutral() -> None:
    adapter, _ = backend()

    uploaded = adapter.upload_files([("/workspace/work/input.csv", b"a,b\n1,2")])
    downloaded = adapter.download_files(["/workspace/work/input.csv"])

    assert uploaded[0].error is None
    assert downloaded[0].content == b"a,b\n1,2"
    assert adapter.upload_files([("relative.txt", b"x")])[0].error == "invalid_path"
    assert adapter.download_files(["relative.txt"])[0].error == "invalid_path"
