from fastapi import APIRouter, Request

router = APIRouter()


def _sessions(request: Request):
    return request.app.state.sessions


@router.get("/projects/{project_id}/sessions")
async def list_sessions(request: Request, project_id: str):
    summaries = await request.app.state.service.sessions(project_id)
    return [s.model_dump() for s in summaries]


@router.get("/sessions/{session_id}")
async def session_detail(request: Request, session_id: str):
    return (await _sessions(request).detail(session_id)).model_dump()


@router.get("/sessions/{session_id}/messages")
async def session_messages(request: Request, session_id: str):
    return await _sessions(request).messages(session_id)


@router.get("/sessions/{session_id}/messages/{uuid}")
async def session_message_full(request: Request, session_id: str, uuid: str):
    return (await _sessions(request).full_message(session_id, uuid)).model_dump()


@router.get("/sessions/{session_id}/agents")
async def session_agents(request: Request, session_id: str):
    return [a.model_dump() for a in await _sessions(request).agents(session_id)]


@router.get("/sessions/{session_id}/agents/{agent_id}/messages")
async def agent_messages(request: Request, session_id: str, agent_id: str):
    return await _sessions(request).agent_messages(session_id, agent_id)
