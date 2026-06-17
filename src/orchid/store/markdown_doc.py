"""Markdown-with-frontmatter storage for the living documents (architecture, spec).

The body is plain markdown — so it diffs cleanly in git — preceded by a JSON
frontmatter block carrying the metadata (version/title/status/timestamps). JSON
frontmatter (not YAML) keeps parsing dependency-free and robust to any title text.

On disk:

    ---
    {
      "version": 3,
      "title": "…",
      "status": "active",
      "created_at": "…",
      "updated_at": "…"
    }
    ---

    <markdown content>

read_doc returns the same dict shape the JSON stores used (metadata + "content"),
so callers are unchanged. write_doc takes that dict.
"""

import json
import os
from pathlib import Path
from typing import Any

_OPEN = "---\n"
_CLOSE = "\n---\n"


def read_doc(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return None
    if not text.startswith(_OPEN):
        return None
    end = text.find(_CLOSE, len(_OPEN))
    if end == -1:
        return None
    try:
        meta = json.loads(text[len(_OPEN):end])
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(meta, dict):
        return None
    body = text[end + len(_CLOSE):].lstrip("\n")
    meta["content"] = body.rstrip("\n")
    return meta


def write_doc(path: Path, data: dict[str, Any]) -> None:
    meta = {k: v for k, v in data.items() if k != "content"}
    content = (data.get("content") or "").strip("\n")
    text = _OPEN + json.dumps(meta, indent=2, ensure_ascii=False) + _CLOSE + "\n" + content + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)
