"""Disk-persisted reviews at <root>/.orchid/reviews/<review_id>.json.

Same pattern as plan_store: thin persistence, the review lifecycle lives in
the API layer and git_tools.
"""

import re
import secrets
from pathlib import Path
from typing import Any

from .jsonio import atomic_write_json, load_json
from .project_store import orchid_dir

_REVIEW_ID_RE = re.compile(r"^rev_[0-9a-f]{6,}$")


def reviews_dir(root: Path) -> Path:
    return orchid_dir(root) / "reviews"


def new_review_id() -> str:
    return "rev_" + secrets.token_hex(6)


def _review_file(root: Path, review_id: str) -> Path | None:
    if not _REVIEW_ID_RE.match(review_id):
        return None
    return reviews_dir(root) / f"{review_id}.json"


def read_review(root: Path, review_id: str) -> dict[str, Any] | None:
    path = _review_file(root, review_id)
    if path is None:
        return None
    data = load_json(path, default=None)
    return data if isinstance(data, dict) and data.get("id") == review_id else None


def write_review(root: Path, review: dict[str, Any]) -> None:
    path = _review_file(root, review.get("id", ""))
    if path is None:
        raise ValueError(f"invalid review id: {review.get('id')!r}")
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, review)


def list_reviews(root: Path) -> list[dict[str, Any]]:
    d = reviews_dir(root)
    if not d.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for f in d.glob("rev_*.json"):
        data = load_json(f, default=None)
        if isinstance(data, dict) and "id" in data:
            out.append(data)
    out.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return out


def delete_review(root: Path, review_id: str) -> bool:
    path = _review_file(root, review_id)
    if path is None or not path.exists():
        return False
    path.unlink()
    return True
