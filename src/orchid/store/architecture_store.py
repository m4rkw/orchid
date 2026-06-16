"""Single living architecture definition per project at <root>/.orchid/architecture.json.

The architecture describes HOW the system is built — its structure, components,
boundaries, and the decisions that shape them. It PRECEDES and INFORMS the
specification: the architecture is the foundation (how it's built), the spec is
what it should do. Both are living documents; agents keep them current, and the
spec must stay consistent with the architecture. Same storage pattern as
spec_store / plan_store: thin persistence, atomic writes.
"""

from pathlib import Path
from typing import Any

from .jsonio import atomic_write_json, load_json
from .project_store import orchid_dir


def architecture_path(root: Path) -> Path:
    return orchid_dir(root) / "architecture.json"


def read_architecture(root: Path) -> dict[str, Any] | None:
    data = load_json(architecture_path(root), default=None)
    return data if isinstance(data, dict) and data.get("content") is not None else None


def write_architecture(root: Path, arch: dict[str, Any]) -> None:
    path = architecture_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, arch)
