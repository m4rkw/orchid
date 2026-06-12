import secrets
from datetime import datetime, timezone
from pathlib import Path

from .jsonio import atomic_write_json, load_json
from .paths import canonicalize

_EMPTY = {"version": 1, "projects": []}


def new_project_id() -> str:
    return "prj_" + secrets.token_hex(6)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Registry:
    """Global index of onboarded project roots (~/.orchid/registry.json).

    Holds paths only — names and settings live in each project's .orchid/.
    """

    def __init__(self, path: Path):
        self._path = path

    def _load(self) -> dict:
        data = load_json(self._path, default=None)
        if not isinstance(data, dict) or "projects" not in data:
            return {**_EMPTY, "projects": []}
        return data

    def list(self) -> list[dict]:
        return list(self._load()["projects"])

    def find(self, project_id: str) -> dict | None:
        return next((e for e in self.list() if e["id"] == project_id), None)

    def find_by_root(self, root: str | Path) -> dict | None:
        resolved = str(canonicalize(root))
        return next((e for e in self.list() if e["root"] == resolved), None)

    def add(self, project_id: str, root: str | Path) -> dict:
        existing = self.find_by_root(root)
        if existing:
            return existing
        data = self._load()
        entry = {"id": project_id, "root": str(canonicalize(root)), "added_at": _now()}
        data["projects"].append(entry)
        atomic_write_json(self._path, data)
        return entry

    def remove(self, project_id: str) -> bool:
        data = self._load()
        before = len(data["projects"])
        data["projects"] = [e for e in data["projects"] if e["id"] != project_id]
        if len(data["projects"]) == before:
            return False
        atomic_write_json(self._path, data)
        return True
