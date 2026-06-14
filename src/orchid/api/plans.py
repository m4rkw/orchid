from pathlib import Path

from fastapi import APIRouter, Request

from ..services import ApiError, ProjectService
from ..store import plan_store

router = APIRouter()


def _service(request: Request) -> ProjectService:
    return request.app.state.service


def _root(request: Request, project_id: str) -> Path:
    return Path(_service(request).get_entry(project_id)["root"])  # raises 404 if unknown


@router.get("/projects/{project_id}/plans")
async def list_project_plans(request: Request, project_id: str):
    return plan_store.list_plans(_root(request, project_id))


@router.get("/projects/{project_id}/plans/{plan_id}")
async def get_project_plan(request: Request, project_id: str, plan_id: str):
    plan = plan_store.read_plan(_root(request, project_id), plan_id)
    if plan is None:
        raise ApiError("PLAN_NOT_FOUND", f"no plan {plan_id} in project {project_id}", 404)
    return plan
