from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from ..services import ApiError, ProjectService

router = APIRouter()


def _service(request: Request) -> ProjectService:
    return request.app.state.service


class CreateProjectBody(BaseModel):
    path: str
    name: str | None = None


@router.get("/projects")
async def list_projects(request: Request):
    return [p.model_dump() for p in await _service(request).list_projects()]


@router.post("/projects", status_code=201)
async def create_project(request: Request, body: CreateProjectBody):
    project, created = await _service(request).create(body.path, body.name)
    if not created:
        raise ApiError("ALREADY_REGISTERED", f"already registered as '{project.name}'", 409)
    return project.model_dump()


@router.delete("/projects/{project_id}", status_code=204)
async def delete_project(request: Request, project_id: str):
    await _service(request).remove(project_id)
    return Response(status_code=204)
