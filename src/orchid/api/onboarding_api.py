from fastapi import APIRouter, Request
from pydantic import BaseModel

from ..claude.transcript import normalize_record

router = APIRouter()


class PromptBody(BaseModel):
    prompt: str


@router.post("/onboarding/prompt", status_code=202)
async def onboarding_prompt(request: Request, body: PromptBody):
    await request.app.state.onboarding.prompt(body.prompt)
    return {}


@router.get("/onboarding/messages")
async def onboarding_messages(request: Request):
    """Recover the onboarding chat over REST (survives reloads / WS gaps)."""
    onboarding = request.app.state.onboarding
    sid = onboarding.session_id
    running = onboarding.state == "running"
    if not sid:
        return {"messages": [], "running": running}
    records = await request.app.state.catalog.session_messages(
        sid, request.app.state.settings.orchid_home
    )
    messages = [m.model_dump() for r in records if (m := normalize_record(r)) is not None]
    return {"messages": messages, "running": running}


@router.post("/onboarding/reset")
async def onboarding_reset(request: Request):
    await request.app.state.onboarding.reset()
    return {}
