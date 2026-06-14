"""Disk-persisted per-session usage at <root>/.orchid/usage/<sid>.json.

Cost/turn data the SDK already reports per turn (ResultMessage), accumulated so
it survives the session. Thin persistence, same pattern as review_store —
the .orchid/.gitignore (written at init) already excludes this directory.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .jsonio import atomic_write_json, load_json
from .project_store import orchid_dir


def usage_dir(root: Path) -> Path:
    return orchid_dir(root) / "usage"


def _usage_file(root: Path, session_id: str) -> Path | None:
    # Session ids are SDK uuids; guard against path traversal regardless.
    if not session_id or "/" in session_id or "\\" in session_id or session_id.startswith("."):
        return None
    return usage_dir(root) / f"{session_id}.json"


def read_usage(root: Path, session_id: str) -> dict[str, Any]:
    path = _usage_file(root, session_id)
    if path is None:
        return {}
    data = load_json(path, default=None)
    return data if isinstance(data, dict) else {}


def add_turn(root: Path, session_id: str, *, cost_usd: float, duration_ms: int,
             is_error: bool) -> dict[str, Any]:
    """Accumulate one completed turn. Serialized per session by the owning driver
    task, so there is no cross-write race on this file."""
    path = _usage_file(root, session_id)
    if path is None:
        return {}
    cur = read_usage(root, session_id)
    cur["session_id"] = session_id
    cur["total_cost_usd"] = round((cur.get("total_cost_usd") or 0.0) + (cost_usd or 0.0), 6)
    cur["total_duration_ms"] = (cur.get("total_duration_ms") or 0) + (duration_ms or 0)
    cur["turns"] = (cur.get("turns") or 0) + 1
    if is_error:
        cur["errors"] = (cur.get("errors") or 0) + 1
    cur["updated_at"] = datetime.now(timezone.utc).isoformat()
    atomic_write_json(path, cur)
    return cur


def project_usage(root: Path) -> dict[str, Any]:
    """Roll up every session usage file in the project."""
    d = usage_dir(root)
    total_cost, total_turns, sessions = 0.0, 0, 0
    if d.is_dir():
        for f in d.glob("*.json"):
            data = load_json(f, default=None)
            if isinstance(data, dict):
                total_cost += data.get("total_cost_usd") or 0.0
                total_turns += data.get("turns") or 0
                sessions += 1
    return {"total_cost_usd": round(total_cost, 6), "turns": total_turns, "sessions": sessions}
