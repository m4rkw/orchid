from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .jsonio import atomic_write_json, load_json

ORCHID_DIRNAME = ".orchid"


def orchid_dir(root: Path) -> Path:
    return root / ORCHID_DIRNAME


def _project_file(root: Path) -> Path:
    return orchid_dir(root) / "project.json"


def _sessions_file(root: Path) -> Path:
    return orchid_dir(root) / "sessions.json"


def init_project(root: Path, project_id: str, name: str) -> dict:
    """Create .orchid/ state in a project root (idempotent)."""
    d = orchid_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    gitignore = d / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("*\n")
    existing = read_project_file(root)
    if existing:
        return existing
    data = {
        "version": 1,
        "id": project_id,
        "name": name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "settings": {"model": None, "permission_mode": "acceptEdits"},
        "intent": None,
        "goal": None,
        "review_mode": None,
        "project_type": None,
        "children": [],
    }
    atomic_write_json(_project_file(root), data)
    return data


def read_project_file(root: Path) -> dict | None:
    data = load_json(_project_file(root), default=None)
    return data if isinstance(data, dict) and "id" in data else None


def write_project_file(root: Path, data: dict) -> None:
    atomic_write_json(_project_file(root), data)


def get_session_flags(root: Path) -> dict[str, dict[str, Any]]:
    data = load_json(_sessions_file(root), default=None)
    if not isinstance(data, dict):
        return {}
    sessions = data.get("sessions")
    return sessions if isinstance(sessions, dict) else {}


def is_orchid_session(root: Path, session_id: str) -> bool:
    """True only for sessions Orchid itself created (orchestrator session / fork).

    Orchid never adopts terminal-started transcripts that merely happen to live
    in the same directory, so the ``created_by`` flag is the single source of
    truth for what Orchid is allowed to surface and stream.
    """
    return get_session_flags(root).get(session_id, {}).get("created_by") == "orchid"


def set_session_flags(root: Path, session_id: str, **flags: Any) -> dict[str, Any]:
    """Sparse upsert: only sessions with explicit flags get an entry."""
    sessions = get_session_flags(root)
    entry = sessions.get(session_id, {})
    if not entry and "first_seen_at" not in flags:
        entry["first_seen_at"] = datetime.now(timezone.utc).isoformat()
    entry.update(flags)
    sessions[session_id] = entry
    atomic_write_json(_sessions_file(root), {"version": 1, "sessions": sessions})
    return entry
