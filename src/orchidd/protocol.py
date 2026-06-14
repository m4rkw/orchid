"""NDJSON protocol for orchidd IPC.

Each message is a single JSON object terminated by newline.
Requests carry an `id` and `op`; responses echo the `id`.
"""

import json
from typing import Any

VALID_OPS = frozenset({
    "ping",
    "check_access",
    "read_file",
    "write_file",
    "edit_file",
    "delete_file",
    "mkdir",
    "chmod",
    "exec",
    "stat",
})


def encode(msg: dict[str, Any]) -> bytes:
    return json.dumps(msg, separators=(",", ":")).encode() + b"\n"


def decode(line: bytes) -> dict[str, Any]:
    return json.loads(line)


def ok_response(request_id: str, result: Any = None) -> dict[str, Any]:
    return {"id": request_id, "ok": True, "result": result or {}}


def error_response(request_id: str, code: str, message: str) -> dict[str, Any]:
    return {"id": request_id, "ok": False, "error": {"code": code, "message": message}}
