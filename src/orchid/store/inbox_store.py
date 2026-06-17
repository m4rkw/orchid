"""Disk-persisted inbox work-items at <root>/.orchid/inbox/<item_id>.json.

The inbox is a generic decision-surface: any program (Orchid itself, or an
external tool like docmgr) POSTs a work item that needs a human decision —
grouped, with a set of option "buttons" and arbitrary `context` handed back to
the originator. Orchid surfaces it, records the chosen option, and the
originating program polls for resolutions and acts on them. Orchid never
executes the decision itself.

Same thin-persistence pattern as review_store/plan_store: the lifecycle lives in
the API layer.
"""

import re
import secrets
from pathlib import Path
from typing import Any

from .jsonio import atomic_write_json, load_json
from .project_store import orchid_dir

_ITEM_ID_RE = re.compile(r"^inb_[0-9a-f]{6,}$")


def inbox_dir(root: Path) -> Path:
    return orchid_dir(root) / "inbox"


def new_item_id() -> str:
    return "inb_" + secrets.token_hex(6)


def _item_file(root: Path, item_id: str) -> Path | None:
    if not _ITEM_ID_RE.match(item_id):
        return None
    return inbox_dir(root) / f"{item_id}.json"


def read_item(root: Path, item_id: str) -> dict[str, Any] | None:
    path = _item_file(root, item_id)
    if path is None:
        return None
    data = load_json(path, default=None)
    return data if isinstance(data, dict) and data.get("id") == item_id else None


def write_item(root: Path, item: dict[str, Any]) -> None:
    path = _item_file(root, item.get("id", ""))
    if path is None:
        raise ValueError(f"invalid inbox item id: {item.get('id')!r}")
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, item)


def list_items(root: Path) -> list[dict[str, Any]]:
    d = inbox_dir(root)
    if not d.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for f in d.glob("inb_*.json"):
        data = load_json(f, default=None)
        if isinstance(data, dict) and "id" in data:
            out.append(data)
    # Newest-first, then a stable pass to float pending items to the top.
    out.sort(key=lambda i: i.get("created_at") or "", reverse=True)
    out.sort(key=lambda i: i.get("status") != "pending")
    return out


def delete_item(root: Path, item_id: str) -> bool:
    path = _item_file(root, item_id)
    if path is None or not path.exists():
        return False
    path.unlink()
    return True
