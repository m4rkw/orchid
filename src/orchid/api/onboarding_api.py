from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter()


class PromptBody(BaseModel):
    prompt: str


@router.post("/onboarding/prompt", status_code=202)
async def onboarding_prompt(request: Request, body: PromptBody):
    await request.app.state.onboarding.prompt(body.prompt)
    return {}


@router.post("/onboarding/reset")
async def onboarding_reset(request: Request):
    await request.app.state.onboarding.reset()
    return {}
