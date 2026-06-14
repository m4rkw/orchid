"""ACL storage, validation, and enforcement for orchidd.

The ACL file lives at ~/.orchid/orchidd_acl.json and is read on every
request (it's small). Orchid writes it; orchidd only reads and enforces.
"""

import json
import logging
import os
import shlex
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def _canonicalize(p: str | Path) -> Path:
    return Path(str(p)).expanduser().resolve()


def load_acl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        return data.get("grants", [])
    except (json.JSONDecodeError, OSError, KeyError):
        log.warning("corrupt or unreadable ACL at %s — denying all", path)
        return []


def save_acl(path: Path, grants: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps({"version": 1, "grants": grants}, indent=2) + "\n")
    os.replace(tmp, path)


def find_grant(grants: list[dict[str, Any]], project_root: str) -> dict[str, Any] | None:
    root = _canonicalize(project_root)
    for g in grants:
        if _canonicalize(g["project_root"]) == root:
            return g
    return None


def check_file_op(grant: dict[str, Any], op: str, target_path: str) -> str | None:
    """Return None if allowed, or an error message if denied."""
    ops = grant.get("operations", {})
    op_key = {
        "read_file": "file_read",
        "write_file": "file_write",
        "edit_file": "file_write",
        "delete_file": "file_delete",
        "mkdir": "file_write",
        "stat": "file_read",
    }.get(op)
    if not op_key:
        return f"unknown file operation: {op}"
    if not ops.get(op_key):
        return f"{op_key} not granted for {grant['project_root']}"
    canon = _canonicalize(target_path)
    root = _canonicalize(grant["project_root"])
    try:
        canon.relative_to(root)
    except ValueError:
        return f"path {canon} is outside project root {root}"
    return None


def check_exec(grant: dict[str, Any], command: list[str]) -> str | None:
    """Return None if the command is allowed by the exec whitelist, else an error."""
    ops = grant.get("operations", {})
    allowed = ops.get("exec", [])
    if not allowed:
        return f"no exec commands granted for {grant['project_root']}"
    cmd_str = shlex.join(command)
    for pattern in allowed:
        if pattern == cmd_str:
            return None
        if pattern.endswith(" *"):
            prefix = pattern[:-2]
            if cmd_str == prefix or cmd_str.startswith(prefix + " "):
                return None
    return f"command not in exec whitelist: {cmd_str}"


def find_grant_for_path(grants: list[dict[str, Any]], target_path: str) -> dict[str, Any] | None:
    """Find the grant whose project_root contains target_path."""
    canon = _canonicalize(target_path)
    for g in grants:
        root = _canonicalize(g["project_root"])
        try:
            canon.relative_to(root)
            return g
        except ValueError:
            continue
    return None


def find_grant_for_exec(grants: list[dict[str, Any]], command: list[str]) -> dict[str, Any] | None:
    """Find the first grant whose exec whitelist allows this command."""
    for g in grants:
        if check_exec(g, command) is None:
            return g
    return None
