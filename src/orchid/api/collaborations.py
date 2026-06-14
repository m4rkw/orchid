from fastapi import APIRouter, Request

from ..claude.collaboration import CollaborationManager
from ..services import ApiError

router = APIRouter()


def _manager(request: Request) -> CollaborationManager:
    return request.app.state.collab_manager


@router.get("/collaborations/eligible-projects")
async def eligible_projects(request: Request):
    """Projects that have at least one Orchid-owned session (can join a collab)."""
    service = request.app.state.service
    projects = await service.list_projects()
    eligible = []
    for p in projects:
        if p.missing:
            continue
        sessions = await service.sessions(p.id)
        if sessions:
            eligible.append({"id": p.id, "name": p.name, "session_count": len(sessions)})
    return eligible


@router.get("/collaborations")
async def list_collaborations(request: Request):
    return _manager(request).list_all()


@router.post("/collaborations")
async def create_collaboration(request: Request):
    body = await request.json()
    project_ids = body.get("project_ids", [])
    if len(project_ids) < 2:
        raise ApiError("TOO_FEW_PARTICIPANTS", "at least 2 projects required", 400)
    try:
        collab = await _manager(request).create(project_ids)
    except ValueError as exc:
        raise ApiError("INVALID_REQUEST", str(exc), 400)
    return collab


@router.get("/collaborations/{collab_id}")
async def get_collaboration(request: Request, collab_id: str):
    try:
        return _manager(request).get(collab_id)
    except ValueError:
        raise ApiError("COLLAB_NOT_FOUND", f"no collaboration {collab_id}", 404)


@router.post("/collaborations/{collab_id}/messages")
async def send_collab_message(request: Request, collab_id: str):
    body = await request.json()
    text = body.get("message", "").strip()
    if not text:
        raise ApiError("MISSING_MESSAGE", "message is required", 400)
    try:
        msg = await _manager(request).send_message(collab_id, text)
    except ValueError as exc:
        raise ApiError("INVALID_REQUEST", str(exc), 400)
    return msg


@router.post("/collaborations/{collab_id}/continue")
async def continue_collaboration(request: Request, collab_id: str):
    body = await request.json()
    target_index = body.get("target_index")
    try:
        await _manager(request).continue_relay(collab_id, target_index)
    except ValueError as exc:
        raise ApiError("INVALID_REQUEST", str(exc), 400)
    return {"status": "ok"}


@router.post("/collaborations/{collab_id}/auto-continue")
async def set_auto_continue(request: Request, collab_id: str):
    body = await request.json()
    value = body.get("value", True)
    try:
        await _manager(request).set_auto_continue(collab_id, bool(value))
    except ValueError as exc:
        raise ApiError("INVALID_REQUEST", str(exc), 400)
    return {"status": "ok"}


@router.post("/collaborations/{collab_id}/end")
async def end_collaboration(request: Request, collab_id: str):
    try:
        return await _manager(request).end(collab_id)
    except ValueError as exc:
        raise ApiError("INVALID_REQUEST", str(exc), 400)


@router.delete("/collaborations/{collab_id}")
async def delete_collaboration(request: Request, collab_id: str):
    try:
        await _manager(request).delete(collab_id)
    except ValueError as exc:
        raise ApiError("COLLAB_NOT_FOUND", str(exc), 404)
    return {"status": "ok"}
