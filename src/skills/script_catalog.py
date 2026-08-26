"""Discover the reviewed Python entrypoints shipped with enabled Skills."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ScriptEntry:
    skill_id: str
    script_name: str
    source_path: Path
    runtime_path: str


class ScriptCatalog:
    """An immutable startup whitelist; it is not a user-provided manifest."""

    def __init__(self, skills_root: Path, enabled_skills: list[str]) -> None:
        self._entries: dict[tuple[str, str], ScriptEntry] = {}
        root = skills_root.resolve()
        for skill_id in enabled_skills:
            scripts_dir = (root / skill_id / "scripts").resolve()
            if not scripts_dir.is_dir() or not scripts_dir.is_relative_to(root):
                continue
            for source_path in scripts_dir.rglob("*.py"):
                if source_path.is_symlink() or not source_path.is_file():
                    continue
                resolved = source_path.resolve()
                if not resolved.is_relative_to(scripts_dir):
                    continue
                name = source_path.relative_to(scripts_dir).as_posix()
                self._entries[(skill_id, name)] = ScriptEntry(
                    skill_id=skill_id,
                    script_name=name,
                    source_path=resolved,
                    runtime_path=f"/workspace/skills/{skill_id}/scripts/{name}",
                )

    def resolve(self, skill_id: str, script_name: str) -> ScriptEntry:
        if "/" in skill_id or "\\" in skill_id or ".." in script_name or script_name.startswith("/"):
            raise ValueError("Invalid Skill script identifier")
        entry = self._entries.get((skill_id, script_name))
        if entry is None:
            raise ValueError("Skill script is not enabled")
        return entry
