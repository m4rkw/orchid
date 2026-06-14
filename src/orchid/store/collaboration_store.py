"""Disk-persisted collaboration sessions at ~/.orchid/collaborations/<id>.json.

Collaborations are cross-project, so they live under orchid_home rather than a
single project root.  Each file holds the full state: participants, messages,
and turn-management metadata.
"""

import secrets
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .jsonio import atomic_write_json, load_json

_COLLAB_ID_RE = re.compile(r"^col_[0-9a-f]{12}$")
_MSG_ID_RE = re.compile(r"^cmsg_[0-9a-f]{8}$")


def collabs_dir(orchid_home: Path) -> Path:
    return orchid_home / "collaborations"


def new_collab_id() -> str:
    return "col_" + secrets.token_hex(6)


def new_message_id() -> str:
    return "cmsg_" + secrets.token_hex(4)


def _collab_file(orchid_home: Path, collab_id: str) -> Path | None:
    if not _COLLAB_ID_RE.match(collab_id):
        return None
    return collabs_dir(orchid_home) / f"{collab_id}.json"


def read_collab(orchid_home: Path, collab_id: str) -> dict[str, Any] | None:
    path = _collab_file(orchid_home, collab_id)
    if path is None:
        return None
    data = load_json(path, default=None)
    return data if isinstance(data, dict) and data.get("id") == collab_id else None


def write_collab(orchid_home: Path, collab: dict[str, Any]) -> None:
    path = _collab_file(orchid_home, collab.get("id", ""))
    if path is None:
        raise ValueError(f"invalid collab id: {collab.get('id')!r}")
    atomic_write_json(path, collab)


def list_collabs(orchid_home: Path) -> list[dict[str, Any]]:
    d = collabs_dir(orchid_home)
    if not d.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for f in d.glob("col_*.json"):
        data = load_json(f, default=None)
        if isinstance(data, dict) and "id" in data:
            out.append(data)
    out.sort(key=lambda c: c.get("created_at") or "", reverse=True)
    return out


def delete_collab(orchid_home: Path, collab_id: str) -> bool:
    path = _collab_file(orchid_home, collab_id)
    if path is None or not path.exists():
        return False
    path.unlink()
    return True


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_collab(title: str, participants: list[dict[str, Any]]) -> dict[str, Any]:
    ts = now_iso()
    return {
        "id": new_collab_id(),
        "title": title,
        "participants": participants,
        "messages": [],
        "state": "active",
        "auto_continue": True,
        "created_at": ts,
        "updated_at": ts,
    }


def add_message(
    collab: dict[str, Any],
    sender: str,
    sender_label: str,
    content: str,
) -> dict[str, Any]:
    msg = {
        "id": new_message_id(),
        "sender": sender,
        "sender_label": sender_label,
        "content": content,
        "timestamp": now_iso(),
    }
    collab["messages"].append(msg)
    collab["updated_at"] = msg["timestamp"]
    return msg
