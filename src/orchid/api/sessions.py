from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

router = APIRouter()


def _sessions(request: Request):
    return request.app.state.sessions


def _manager(request: Request):
    return request.app.state.driver_manager


class NewSessionBody(BaseModel):
    prompt: str
    model: str | None = None
    permission_mode: str | None = None


class PromptBody(BaseModel):
    prompt: str
    force: bool = False


class RenameBody(BaseModel):
    title: str


class FlagBody(BaseModel):
    value: bool


class ForkBody(BaseModel):
    title: str | None = None


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


@router.post("/projects/{project_id}/sessions", status_code=201)
async def create_session(request: Request, project_id: str, body: NewSessionBody):
    entry = request.app.state.service.get_entry(project_id)
    sid = await _manager(request).create_session(
        entry, body.prompt, model=body.model, permission_mode=body.permission_mode
    )
    return {"session_id": sid}


@router.post("/sessions/{session_id}/prompt", status_code=202)
async def prompt_session(request: Request, session_id: str, body: PromptBody):
    return await _manager(request).prompt(session_id, body.prompt, force=body.force)


@router.post("/sessions/{session_id}/interrupt")
async def interrupt_session(request: Request, session_id: str):
    await _manager(request).interrupt(session_id)
    return {}


@router.post("/sessions/{session_id}/rename")
async def rename_session(request: Request, session_id: str, body: RenameBody):
    await _sessions(request).rename(session_id, body.title)
    return {}


@router.post("/sessions/{session_id}/pin")
async def pin_session(request: Request, session_id: str, body: FlagBody):
    await _sessions(request).set_flag(session_id, pinned=body.value)
    return {}


@router.post("/sessions/{session_id}/archive")
async def archive_session(request: Request, session_id: str, body: FlagBody):
    await _sessions(request).set_flag(session_id, archived=body.value)
    return {}


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(request: Request, session_id: str, force: bool = False):
    await _sessions(request).delete(session_id, force=force)
    return Response(status_code=204)


@router.post("/sessions/{session_id}/fork", status_code=201)
async def fork_session(request: Request, session_id: str, body: ForkBody):
    new_sid = await _sessions(request).fork(session_id, title=body.title)
    return {"session_id": new_sid}
