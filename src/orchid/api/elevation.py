"""REST endpoints for managing orchidd ACL grants."""

import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ..orchidd.client import OrchiddClient, OrchiddError
from ..services import ApiError
from ..store.paths import canonicalize

router = APIRouter(tags=["elevation"])


def _acl_path(request: Request) -> Path:
    return request.app.state.settings.orchid_home / "orchidd_acl.json"


def _client(request: Request) -> OrchiddClient:
    return request.app.state.orchidd_client


def _load_acl(request: Request) -> list[dict[str, Any]]:
    from orchidd.acl import load_acl
    return load_acl(_acl_path(request))


def _save_acl(request: Request, grants: list[dict[str, Any]]) -> None:
    from orchidd.acl import save_acl
    save_acl(_acl_path(request), grants)


class GrantBody(BaseModel):
    operations: dict[str, Any]
    permanent: bool = True


class ExecGrantBody(BaseModel):
    command: str


def needs_elevation(root: Path) -> bool:
    try:
        return root.stat().st_uid != os.getuid()
    except OSError:
        return False


@router.get("/projects/{project_id}/elevation")
async def get_elevation(project_id: str, request: Request):
    service = request.app.state.service
    entry = service.get_entry(project_id)
    root = canonicalize(entry["root"])
    elevated = needs_elevation(root)

    client = _client(request)
    orchidd_available = await client.is_available()

    grants = _load_acl(request)
    from orchidd.acl import find_grant
    grant = find_grant(grants, str(root))

    return {
        "elevated": elevated,
        "orchidd_available": orchidd_available,
        "grant": grant,
        "owner": _owner_info(root) if elevated else None,
    }


@router.post("/projects/{project_id}/elevation")
async def grant_elevation(project_id: str, body: GrantBody, request: Request):
    service = request.app.state.service
    entry = service.get_entry(project_id)
    root = canonicalize(entry["root"])

    client = _client(request)
    if not await client.is_available():
        raise ApiError("ORCHIDD_UNAVAILABLE", "orchidd is not running", 503)

    grants = _load_acl(request)
    from orchidd.acl import find_grant
    existing = find_grant(grants, str(root))
    if existing:
        existing["operations"] = body.operations
        existing["permanent"] = body.permanent
    else:
        grants.append({
            "id": f"grant_{secrets.token_hex(6)}",
            "project_root": str(root),
            "project_id": project_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "permanent": body.permanent,
            "operations": body.operations,
        })
    _save_acl(request, grants)
    return {"ok": True, "grant_count": len(grants)}


@router.post("/projects/{project_id}/elevation/exec")
async def add_exec_command(project_id: str, body: ExecGrantBody, request: Request):
    """Add a command to the exec whitelist for this project."""
    service = request.app.state.service
    entry = service.get_entry(project_id)
    root = canonicalize(entry["root"])

    grants = _load_acl(request)
    from orchidd.acl import find_grant
    grant = find_grant(grants, str(root))
    if grant is None:
        raise ApiError("NO_GRANT", "no elevation grant exists for this project — create one first", 404)

    ops = grant.setdefault("operations", {})
    exec_list = ops.setdefault("exec", [])
    if body.command not in exec_list:
        exec_list.append(body.command)
        _save_acl(request, grants)
    return {"ok": True, "exec": exec_list}


@router.delete("/projects/{project_id}/elevation")
async def revoke_elevation(project_id: str, request: Request):
    service = request.app.state.service
    entry = service.get_entry(project_id)
    root = canonicalize(entry["root"])

    grants = _load_acl(request)
    root_str = str(root)
    before = len(grants)
    grants = [g for g in grants if str(canonicalize(g["project_root"])) != root_str]
    if len(grants) == before:
        raise ApiError("NO_GRANT", "no grant found for this project", 404)
    _save_acl(request, grants)
    return {"ok": True, "grant_count": len(grants)}


def _owner_info(root: Path) -> dict[str, str]:
    import grp
    import pwd
    s = root.stat()
    try:
        owner = pwd.getpwuid(s.st_uid).pw_name
    except KeyError:
        owner = str(s.st_uid)
    try:
        group = grp.getgrgid(s.st_gid).gr_name
    except KeyError:
        group = str(s.st_gid)
    return {"user": owner, "group": group, "uid": s.st_uid, "gid": s.st_gid}
