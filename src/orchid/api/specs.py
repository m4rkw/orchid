from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ..services import ApiError, ProjectService
from ..store import spec_store

router = APIRouter()


def _service(request: Request) -> ProjectService:
    return request.app.state.service


def _root(request: Request, project_id: str) -> Path:
    return Path(_service(request).get_entry(project_id)["root"])


@router.get("/projects/{project_id}/spec")
async def get_spec(request: Request, project_id: str):
    spec = spec_store.read_spec(_root(request, project_id))
    if spec is None:
        raise ApiError("SPEC_NOT_FOUND", f"no spec for project {project_id}", 404)
    return spec


class SpecBody(BaseModel):
    title: str | None = None
    content: str


@router.put("/projects/{project_id}/spec")
async def put_spec(request: Request, project_id: str, body: SpecBody):
    root = _root(request, project_id)
    now = datetime.now(timezone.utc).isoformat()
    existing = spec_store.read_spec(root)
    if existing:
        existing["content"] = body.content
        existing["version"] = existing.get("version", 0) + 1
        existing["updated_at"] = now
        if body.title is not None:
            existing["title"] = body.title
        spec_store.write_spec(root, existing)
        spec = existing
    else:
        spec = {
            "version": 1,
            "title": body.title or "Specification",
            "content": body.content,
            "status": "active",
            "created_at": now,
            "updated_at": now,
        }
        spec_store.write_spec(root, spec)
    bus = request.app.state.bus
    bus.publish("sidebar", "spec_updated", {"project_id": project_id, "spec": spec})
    return spec
