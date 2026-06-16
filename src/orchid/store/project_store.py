import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .jsonio import atomic_write_json, load_json

ORCHID_DIRNAME = ".orchid"

# Heuristic to lift a documented test command out of AGENTS.md (in backticks).
_TEST_CMD_RE = re.compile(
    r"`([^`\n]*(?:pytest|unittest|npm (?:run )?test|yarn test|pnpm test|go test|"
    r"cargo test|jest|vitest|rspec|phpunit|tox|make test)[^`\n]*)`",
    re.I,
)


def orchid_dir(root: Path) -> Path:
    return root / ORCHID_DIRNAME


def get_test_command(root: Path) -> str | None:
    """The project's test command for on-demand verification: an explicit
    settings.test_command, else a backticked command lifted from AGENTS.md."""
    file = read_project_file(root) or {}
    cmd = ((file.get("settings") or {}).get("test_command") or "").strip()
    if cmd:
        return cmd
    agents = root / "AGENTS.md"
    if agents.is_file():
        try:
            m = _TEST_CMD_RE.search(agents.read_text(errors="replace"))
            if m:
                return m.group(1).strip()
        except OSError:
            pass
    return None


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
