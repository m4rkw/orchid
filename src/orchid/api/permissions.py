from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter()


class PermissionBody(BaseModel):
    behavior: Literal["allow", "deny"]
    message: str | None = None


@router.post("/permissions/{request_id}")
async def resolve_permission(request: Request, request_id: str, body: PermissionBody):
    await request.app.state.driver_manager.resolve_permission(request_id, body.behavior, body.message)
    return {}
