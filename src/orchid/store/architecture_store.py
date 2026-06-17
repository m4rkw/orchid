"""Single living architecture definition per project at <root>/.orchid/architecture.md.

The architecture describes HOW the system is built (structure, components,
boundaries, key decisions). It PRECEDES and INFORMS the specification. Stored as
markdown (JSON frontmatter + body) so it versions cleanly in git; legacy
architecture.json is read as a fallback and migrated to .md on the next write.
"""

from pathlib import Path
from typing import Any

from .jsonio import load_json
from .markdown_doc import read_doc, write_doc
from .project_store import ensure_orchid_gitignore, orchid_dir


def architecture_path(root: Path) -> Path:
    return orchid_dir(root) / "architecture.md"


def _legacy_path(root: Path) -> Path:
    return orchid_dir(root) / "architecture.json"


def read_architecture(root: Path) -> dict[str, Any] | None:
    data = read_doc(architecture_path(root))
    if data and data.get("content") is not None:
        return data
    legacy = load_json(_legacy_path(root), default=None)  # pre-markdown fallback
    return legacy if isinstance(legacy, dict) and legacy.get("content") is not None else None


def write_architecture(root: Path, arch: dict[str, Any]) -> None:
    ensure_orchid_gitignore(root)  # keep the doc tracked in git
    write_doc(architecture_path(root), arch)
    legacy = _legacy_path(root)
    if legacy.exists():  # migrated to markdown — drop the old json
        try:
            legacy.unlink()
        except OSError:
            pass
