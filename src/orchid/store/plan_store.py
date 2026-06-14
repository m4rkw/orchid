"""Disk-persisted plans at <root>/.orchid/plans/<plan_id>.json.

The planner (orchestrator session) reads and writes these via MCP tools, so a
plan survives the orchestrator's context window — losing the conversation does
not lose the plan. This module is thin persistence only; plan construction and
timestamping live in claude/planning.py.
"""

import re
import secrets
from pathlib import Path
from typing import Any

from .jsonio import atomic_write_json, load_json
from .project_store import orchid_dir

_PLAN_ID_RE = re.compile(r"^pln_[0-9a-f]{6,}$")


def plans_dir(root: Path) -> Path:
    return orchid_dir(root) / "plans"


def new_plan_id() -> str:
    return "pln_" + secrets.token_hex(6)


def new_step_id() -> str:
    return "stp_" + secrets.token_hex(4)


def _plan_file(root: Path, plan_id: str) -> Path | None:
    # plan_id reaches here from URLs and tool args; never let it escape the dir.
    if not _PLAN_ID_RE.match(plan_id):
        return None
    return plans_dir(root) / f"{plan_id}.json"


def read_plan(root: Path, plan_id: str) -> dict[str, Any] | None:
    path = _plan_file(root, plan_id)
    if path is None:
        return None
    data = load_json(path, default=None)
    return data if isinstance(data, dict) and data.get("id") == plan_id else None


def write_plan(root: Path, plan: dict[str, Any]) -> None:
    path = _plan_file(root, plan.get("id", ""))
    if path is None:
        raise ValueError(f"invalid plan id: {plan.get('id')!r}")
    atomic_write_json(path, plan)


def list_plans(root: Path) -> list[dict[str, Any]]:
    d = plans_dir(root)
    if not d.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for f in d.glob("pln_*.json"):
        data = load_json(f, default=None)
        if isinstance(data, dict) and "id" in data:
            out.append(data)
    out.sort(key=lambda p: p.get("updated_at") or "", reverse=True)
    return out


def delete_plan(root: Path, plan_id: str) -> bool:
    path = _plan_file(root, plan_id)
    if path is None or not path.exists():
        return False
    path.unlink()
    return True
