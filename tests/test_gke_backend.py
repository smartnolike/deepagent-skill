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


class FakeConnector:
    def __init__(self, files: FakeFiles) -> None:
        self.files = files
        self.calls: list[tuple[str, str, dict, int]] = []

    def send_request(self, method: str, endpoint: str, *, files: dict, timeout: int) -> None:
        self.calls.append((method, endpoint, files, timeout))
        filename, content = files["file"]
        self.files.values[filename] = content


class FakeCommands:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def run(self, command: str, timeout: int):
        self.calls.append((command, timeout))
        return SimpleNamespace(stdout="created\n", stderr="warning\n", exit_code=0)


def backend() -> tuple[GkeSandboxBackend, SimpleNamespace]:
    files = FakeFiles()
    sandbox = SimpleNamespace(
        claim_name="claim-1", files=files, commands=FakeCommands(), connector=FakeConnector(files)
    )
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
    adapter, sandbox = backend()

    uploaded = adapter.upload_files([("/workspace/work/input.csv", b"a,b\n1,2")])
    downloaded = adapter.download_files(["/workspace/work/input.csv"])

    assert uploaded[0].error is None
    assert downloaded[0].content == b"a,b\n1,2"
    assert sandbox.connector.calls == [
        ("POST", "upload", {"file": ("work/input.csv", b"a,b\n1,2")}, 60)
    ]
    assert adapter.upload_files([("relative.txt", b"x")])[0].error == "invalid_path"
    assert adapter.download_files(["relative.txt"])[0].error == "invalid_path"


def test_file_aliases_are_translated_to_the_runtime_workspace_root() -> None:
    adapter, sandbox = backend()
    sandbox.files.values["skill-packages/example/SKILL.md"] = b"instructions"
    sandbox.files.values["output/report.xlsx"] = b"xlsx"

    assert adapter.download_files(["/skill-packages/example/SKILL.md"])[0].content == b"instructions"
    assert adapter.read_file("/workspace/output/report.xlsx") == b"xlsx"
