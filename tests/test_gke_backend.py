from types import SimpleNamespace
import uuid

import pytest

from config.sandbox_settings import GkeAgentSandboxSettings
from sandbox.gke_backend import GkeSandboxBackend


class FakeFiles:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}
        self.entries: dict[str, list[SimpleNamespace]] = {}

    def read(self, path: str) -> bytes:
        return self.values[path]

    def list(self, path: str) -> list[SimpleNamespace]:
        return self.entries[path]


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


def backend() -> tuple[GkeSandboxBackend, SimpleNamespace, str]:
    files = FakeFiles()
    sandbox = SimpleNamespace(files=files, commands=FakeCommands(), connector=FakeConnector(files))
    settings = GkeAgentSandboxSettings(namespace="test", sandbox_claim_name="deepagent-assistant", router_url="http://router")
    return GkeSandboxBackend(settings, sandbox), sandbox, str(uuid.uuid4())


@pytest.fixture
def configured(monkeypatch):
    conversation_id = str(uuid.uuid4())
    monkeypatch.setattr(
        "sandbox.gke_backend.ensure_config",
        lambda: {"configurable": {"thread_id": conversation_id, "staff_id": "staff_123"}},
    )
    return conversation_id


def test_execute_maps_logical_paths_and_uses_default_timeout(configured: str) -> None:
    adapter, sandbox, _ = backend()
    result = adapter.execute("python /work/script.py")

    root = f"/workspace/staff-workspaces/staff_123/{configured}"
    assert adapter.id == "deepagent-assistant"
    assert sandbox.commands.calls == [
        (f"mkdir -p {root}/work {root}/output && cd {root}/work && export DEEPAGENT_WORKSPACE={root} && python {root}/work/script.py", 120)
    ]
    assert result.output == "created\nwarning\n"


@pytest.mark.parametrize(
    ("logical_path", "expected_suffix"),
    [
        ("/workspace/work/script.py", "/work/script.py"),
        ("/workspace/output/report.xlsx", "/output/report.xlsx"),
        ("/workspace/skill-packages/example/run.py", "/workspace/skill-packages/example/run.py"),
    ],
)
def test_execute_maps_absolute_logical_paths_once(configured: str, logical_path: str, expected_suffix: str) -> None:
    adapter, sandbox, _ = backend()
    adapter.execute(f"python {logical_path}")

    root = f"/workspace/staff-workspaces/staff_123/{configured}"
    expected = (
        f"mkdir -p {root}/work {root}/output && cd {root}/work && export DEEPAGENT_WORKSPACE={root} && "
        f"python {root}{expected_suffix}"
        if "skill-packages" not in logical_path
        else f"mkdir -p {root}/work {root}/output && cd {root}/work && export DEEPAGENT_WORKSPACE={root} && python /workspace/skill-packages/example/run.py"
    )
    assert sandbox.commands.calls == [(expected, 120)]


@pytest.mark.asyncio
async def test_async_execute_accepts_override_timeout(configured: str) -> None:
    adapter, sandbox, _ = backend()
    result = await adapter.aexecute("pwd", timeout=5)

    assert result.exit_code == 0
    assert sandbox.commands.calls[0][1] == 5


def test_ls_uses_runtime_file_api_for_skills(configured: str) -> None:
    adapter, sandbox, _ = backend()
    sandbox.files.entries["skill-packages"] = [
        SimpleNamespace(name="cost-estimation", type="directory", size=0, mod_time=1.0),
        SimpleNamespace(name="README.md", type="file", size=12, mod_time=2.0),
        SimpleNamespace(name="cost-consultant", type="directory", size=0, mod_time=3.0),
    ]

    result = adapter.ls("/workspace/skill-packages")

    assert result.error is None
    assert result.entries == [
        {"path": "/workspace/skill-packages/README.md", "is_dir": False, "size": 12, "modified_at": "1970-01-01T00:00:02+00:00"},
        {"path": "/workspace/skill-packages/cost-consultant/", "is_dir": True, "size": 0, "modified_at": "1970-01-01T00:00:03+00:00"},
        {"path": "/workspace/skill-packages/cost-estimation/", "is_dir": True, "size": 0, "modified_at": "1970-01-01T00:00:01+00:00"},
    ]
    assert sandbox.commands.calls == []


@pytest.mark.asyncio
async def test_als_delegates_to_runtime_file_api(configured: str) -> None:
    adapter, sandbox, _ = backend()
    sandbox.files.entries["skill-packages"] = [SimpleNamespace(name="cost-consultant", type="directory", size=0, mod_time=1.0)]

    result = await adapter.als("/workspace/skill-packages")

    assert result.entries == [
        {"path": "/workspace/skill-packages/cost-consultant/", "is_dir": True, "size": 0, "modified_at": "1970-01-01T00:00:01+00:00"}
    ]


def test_read_uses_runtime_file_api_for_skill_content(configured: str) -> None:
    adapter, sandbox, _ = backend()
    sandbox.files.values["skill-packages/cost-estimation/SKILL.md"] = b"first line\nsecond line\nthird line\n"

    result = adapter.read("/workspace/skill-packages/cost-estimation/SKILL.md", offset=1, limit=1)

    assert result.error is None
    assert result.file_data is not None
    assert result.file_data["content"] == "second line\n"
    assert result.start_line == 2
    assert result.end_line == 2
    assert result.total_lines == 3
    assert result.next_offset == 2
    assert sandbox.commands.calls == []


@pytest.mark.asyncio
async def test_aread_delegates_to_runtime_file_api(configured: str) -> None:
    adapter, sandbox, _ = backend()
    sandbox.files.values["skill-packages/cost-consultant/SKILL.md"] = b"content\n"

    result = await adapter.aread("/workspace/skill-packages/cost-consultant/SKILL.md")

    assert result.file_data is not None
    assert result.file_data["content"] == "content\n"


def test_upload_download_and_artifact_reads_are_conversation_scoped(configured: str) -> None:
    adapter, sandbox, _ = backend()
    root = f"staff-workspaces/staff_123/{configured}"
    sandbox.files.values[f"{root}/output/report.xlsx"] = b"xlsx"
    uploaded = adapter.upload_files([("/work/input.csv", b"a,b\n1,2")])
    downloaded = adapter.download_files(["/work/input.csv"])
    artifact = adapter.read_file_for("staff_123", uuid.UUID(configured), "/workspace/output/report.xlsx")

    assert uploaded[0].error is None
    assert downloaded[0].content == b"a,b\n1,2"
    assert artifact == b"xlsx"
    assert sandbox.connector.calls == [("POST", "upload", {"file": (f"{root}/work/input.csv", b"a,b\n1,2")}, 60)]
