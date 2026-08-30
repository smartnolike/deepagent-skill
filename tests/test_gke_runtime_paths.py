import pytest

from sandbox.gke_runtime_paths import GkeRuntimePathError, to_runtime_relative_path


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("/workspace/skill-packages/example/SKILL.md", "skill-packages/example/SKILL.md"),
        ("/workspace/work/input.csv", "work/input.csv"),
        ("/workspace/output/report.xlsx", "output/report.xlsx"),
        ("/skill-packages/example/SKILL.md", "skill-packages/example/SKILL.md"),
        ("/work/input.csv", "work/input.csv"),
        ("/output/report.xlsx", "output/report.xlsx"),
    ],
)
def test_runtime_paths_are_relative_to_workspace(source: str, expected: str) -> None:
    assert to_runtime_relative_path(source) == expected


@pytest.mark.parametrize("path", ["relative.txt", "/etc/passwd", "/workspace/../app/main.py"])
def test_runtime_paths_reject_non_workspace_targets(path: str) -> None:
    with pytest.raises(GkeRuntimePathError):
        to_runtime_relative_path(path)
