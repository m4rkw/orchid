"""Single living specification per project at <root>/.orchid/spec.json.

The spec is the canonical reference for what the project should do. Agents
see it injected into their system prompt and verify work against it. It can
be edited from the web UI or by the orchestrator via MCP tools.
"""

from pathlib import Path
from typing import Any

from .jsonio import atomic_write_json, load_json
from .project_store import orchid_dir


def spec_path(root: Path) -> Path:
    return orchid_dir(root) / "spec.json"


def read_spec(root: Path) -> dict[str, Any] | None:
    data = load_json(spec_path(root), default=None)
    return data if isinstance(data, dict) and data.get("content") is not None else None


def write_spec(root: Path, spec: dict[str, Any]) -> None:
    path = spec_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, spec)
