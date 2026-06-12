from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/projects/{project_id}/sessions")
async def list_sessions(request: Request, project_id: str):
    summaries = await request.app.state.service.sessions(project_id)
    return [s.model_dump() for s in summaries]
