"""Per-project agent-role overrides at <root>/.orchid/agents.json.

Built-in role templates live in code (claude/roles.py); this file stores only
the deltas a user makes per project — which roles are enabled and any field
overrides. Sparse, like sessions.json. The merge with built-ins happens in
claude/roles.py, not here.
"""

from pathlib import Path
from typing import Any

from .jsonio import atomic_write_json, load_json
from .project_store import orchid_dir


def _agents_file(root: Path) -> Path:
    return orchid_dir(root) / "agents.json"


def read_agent_overrides(root: Path) -> dict[str, dict[str, Any]]:
    data = load_json(_agents_file(root), default=None)
    if not isinstance(data, dict):
        return {}
    roles = data.get("roles")
    return roles if isinstance(roles, dict) else {}


def write_agent_overrides(root: Path, roles: dict[str, dict[str, Any]]) -> None:
    atomic_write_json(_agents_file(root), {"version": 1, "roles": roles})
