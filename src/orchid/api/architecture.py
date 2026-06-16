from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ..services import ApiError, ProjectService
from ..store import architecture_store

router = APIRouter()


def _service(request: Request) -> ProjectService:
    return request.app.state.service


def _root(request: Request, project_id: str) -> Path:
    return Path(_service(request).get_entry(project_id)["root"])


@router.get("/projects/{project_id}/architecture")
async def get_architecture(request: Request, project_id: str):
    arch = architecture_store.read_architecture(_root(request, project_id))
    if arch is None:
        raise ApiError("ARCHITECTURE_NOT_FOUND", f"no architecture for project {project_id}", 404)
    return arch


class ArchitectureBody(BaseModel):
    title: str | None = None
    content: str


@router.put("/projects/{project_id}/architecture")
async def put_architecture(request: Request, project_id: str, body: ArchitectureBody):
    root = _root(request, project_id)
    now = datetime.now(timezone.utc).isoformat()
    existing = architecture_store.read_architecture(root)
    if existing:
        existing["content"] = body.content
        existing["version"] = existing.get("version", 0) + 1
        existing["updated_at"] = now
        if body.title is not None:
            existing["title"] = body.title
        architecture_store.write_architecture(root, existing)
        arch = existing
    else:
        arch = {
            "version": 1,
            "title": body.title or "Architecture",
            "content": body.content,
            "status": "active",
            "created_at": now,
            "updated_at": now,
        }
        architecture_store.write_architecture(root, arch)
    bus = request.app.state.bus
    bus.publish("sidebar", "architecture_updated", {"project_id": project_id, "architecture": arch})
    return arch
