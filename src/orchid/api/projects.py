import asyncio
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from ..services import ApiError, ProjectService
from ..store import usage_store

router = APIRouter()


def _service(request: Request) -> ProjectService:
    return request.app.state.service


class CreateProjectBody(BaseModel):
    path: str
    name: str | None = None


class ProjectSettingsPatch(BaseModel):
    model: str | None = None
    permission_mode: str | None = None


class PatchProjectBody(BaseModel):
    name: str | None = None
    settings: ProjectSettingsPatch | None = None
    intent: Literal["adhoc", "goal"] | None = None
    goal: str | None = None
    review_mode: Literal["manual", "autonomous"] | None = None
    project_type: Literal["application", "meta"] | None = None
    children: list[str] | None = None


@router.get("/projects")
async def list_projects(request: Request):
    return [p.model_dump() for p in await _service(request).list_projects()]


@router.post("/projects", status_code=201)
async def create_project(request: Request, body: CreateProjectBody):
    project, created = await _service(request).create(body.path, body.name)
    if not created:
        raise ApiError("ALREADY_REGISTERED", f"already registered as '{project.name}'", 409)
    return project.model_dump()


@router.patch("/projects/{project_id}")
async def patch_project(request: Request, project_id: str, body: PatchProjectBody):
    sent = body.model_fields_set
    project = await _service(request).update(
        project_id,
        name=body.name,
        settings=body.settings.model_dump(exclude_none=True) if body.settings else None,
        intent=body.intent if "intent" in sent else ...,
        goal=body.goal if "goal" in sent else ...,
        review_mode=body.review_mode if "review_mode" in sent else ...,
        project_type=body.project_type if "project_type" in sent else ...,
        children=body.children if "children" in sent else ...,
    )
    return project.model_dump()


@router.delete("/projects/{project_id}", status_code=204)
async def delete_project(request: Request, project_id: str):
    await _service(request).remove(project_id)
    return Response(status_code=204)


@router.get("/projects/{project_id}/activity")
async def project_activity(request: Request, project_id: str, limit: int = 50):
    entry = _service(request).get_entry(project_id)
    root = entry["root"]
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "log", "--all", f"-n{limit}",
            "--format=%H%x00%h%x00%s%x00%an%x00%aI%x00%D",
            cwd=root,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
    except (OSError, asyncio.TimeoutError):
        return []
    commits = []
    for line in out.decode(errors="replace").strip().splitlines():
        parts = line.split("\x00")
        if len(parts) >= 5:
            commits.append({
                "hash": parts[0], "short_hash": parts[1], "message": parts[2],
                "author": parts[3], "date": parts[4],
                "refs": parts[5] if len(parts) > 5 else "",
            })
    return commits


@router.get("/projects/{project_id}/usage")
async def project_usage(request: Request, project_id: str):
    """Rolled-up cost/turn totals across the project's Orchid-driven sessions."""
    root = Path(_service(request).get_entry(project_id)["root"])
    return usage_store.project_usage(root)


class AgentsBody(BaseModel):
    roles: list[dict[str, Any]]


@router.get("/projects/{project_id}/agents")
async def get_project_agents(request: Request, project_id: str):
    return [r.model_dump() for r in _service(request).roles(project_id)]


@router.put("/projects/{project_id}/agents")
async def put_project_agents(request: Request, project_id: str, body: AgentsBody):
    return [r.model_dump() for r in _service(request).set_roles(project_id, body.roles)]
