"""Single living specification per project at <root>/.orchid/spec.md.

The spec is the canonical reference for what the project should do. Agents see it
injected into their system prompt and verify work against it. Stored as markdown
(JSON frontmatter + body) so it versions cleanly in git; legacy spec.json is read
as a fallback and migrated to spec.md on the next write.
"""

from pathlib import Path
from typing import Any

from .jsonio import load_json
from .markdown_doc import read_doc, write_doc
from .project_store import ensure_orchid_gitignore, orchid_dir


def spec_path(root: Path) -> Path:
    return orchid_dir(root) / "spec.md"


def _legacy_path(root: Path) -> Path:
    return orchid_dir(root) / "spec.json"


def read_spec(root: Path) -> dict[str, Any] | None:
    data = read_doc(spec_path(root))
    if data and data.get("content") is not None:
        return data
    legacy = load_json(_legacy_path(root), default=None)  # pre-markdown fallback
    return legacy if isinstance(legacy, dict) and legacy.get("content") is not None else None


def write_spec(root: Path, spec: dict[str, Any]) -> None:
    ensure_orchid_gitignore(root)  # keep the doc tracked in git
    write_doc(spec_path(root), spec)
    legacy = _legacy_path(root)
    if legacy.exists():  # migrated to markdown — drop the old json
        try:
            legacy.unlink()
        except OSError:
            pass
