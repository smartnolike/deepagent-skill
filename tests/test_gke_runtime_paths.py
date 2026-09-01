import base64

import pytest

from sandbox.gke_runtime_paths import ConversationWorkspacePaths, GkeRuntimePathError, to_runtime_relative_path


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("/workspace/skill-packages/example/SKILL.md", "skill-packages/example/SKILL.md"),
        ("/workspace/work/input.csv", "work/input.csv"),
        ("/workspace/output/report.xlsx", "output/report.xlsx"),
    ],
)
def test_runtime_paths_are_relative_to_workspace(source: str, expected: str) -> None:
    assert to_runtime_relative_path(source) == expected


@pytest.mark.parametrize("path", ["relative.txt", "/etc/passwd", "/workspace/../app/main.py"])
def test_runtime_paths_reject_non_workspace_targets(path: str) -> None:
    with pytest.raises(GkeRuntimePathError):
        to_runtime_relative_path(path)


def test_command_mapping_rewrites_base64_logical_paths_but_not_physical_paths() -> None:
    paths = ConversationWorkspacePaths("/workspace/staff-workspaces", "staff_123", "conversation")
    encoded = base64.b64encode(b"/workspace/output/report.xlsx").decode()
    physical = "/workspace/staff-workspaces/staff_123/conversation/output/report.xlsx"

    mapped = paths.map_command(f"echo '{encoded}' {physical}")

    assert base64.b64encode(physical.encode()).decode() in mapped
    assert mapped.endswith(physical)
