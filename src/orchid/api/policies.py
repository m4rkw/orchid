from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ..services import ApiError, ProjectService
from ..store import policy_store

router = APIRouter()


def _service(request: Request) -> ProjectService:
    return request.app.state.service


def _root(request: Request, project_id: str) -> Path:
    return Path(_service(request).get_entry(project_id)["root"])


@router.get("/projects/{project_id}/policy")
async def get_policy(request: Request, project_id: str):
    return policy_store.resolve_policy(_root(request, project_id))


class PolicyBody(BaseModel):
    profile: str | None = None
    plan_approval: str | None = None
    review_strategy: str | None = None
    merge_approval: str | None = None
    gates: dict[str, dict[str, Any]] | None = None


@router.put("/projects/{project_id}/policy")
async def put_policy(request: Request, project_id: str, body: PolicyBody):
    root = _root(request, project_id)
    now = datetime.now(timezone.utc).isoformat()

    if body.profile in policy_store.PRESETS and not any([
        body.plan_approval, body.review_strategy, body.merge_approval, body.gates,
    ]):
        policy = {**policy_store.PRESETS[body.profile], "updated_at": now}
    else:
        existing = policy_store.resolve_policy(root)
        if body.profile and body.profile in policy_store.PRESETS:
            existing = {**policy_store.PRESETS[body.profile]}
        if body.plan_approval:
            existing["plan_approval"] = body.plan_approval
        if body.review_strategy:
            existing["review_strategy"] = body.review_strategy
        if body.merge_approval:
            existing["merge_approval"] = body.merge_approval
        if body.gates:
            existing.setdefault("gates", {}).update(body.gates)
        preset_match = None
        for name, preset in policy_store.PRESETS.items():
            if all(existing.get(k) == preset.get(k)
                   for k in ("plan_approval", "review_strategy", "merge_approval", "gates")):
                preset_match = name
                break
        existing["profile"] = preset_match or "custom"
        existing["updated_at"] = now
        policy = existing

    policy_store.write_policy(root, policy)
    bus = request.app.state.bus
    bus.publish("sidebar", "policy_updated", {"project_id": project_id})
    return policy
