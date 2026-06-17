"""The inbox: a generic human-decision surface.

Any program — Orchid itself or an external tool like docmgr — POSTs a work item
that needs a human decision: a title, an optional grouping, a set of option
"buttons", and an arbitrary `context` blob handed back verbatim on resolution.
Orchid surfaces the item in the web UI, fires a desktop + Pushover notification
with a deep link, and records which option the human chose. The originating
program polls (GET ?status=resolved) and acts on the decisions itself — Orchid
records the outcome but never executes it.

Mirrors the reviews subsystem: thin JSON store + `sidebar` bus events + notify.
"""

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ..services import ApiError, ProjectService
from ..store import inbox_store

router = APIRouter()


def _service(request: Request) -> ProjectService:
    return request.app.state.service


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class InboxOption(BaseModel):
    id: str
    label: str
    detail: str | None = None


class CreateInboxItem(BaseModel):
    source: str
    title: str
    kind: str | None = None
    body: str | None = None
    group_id: str | None = None
    group_label: str | None = None
    options: list[InboxOption] = []
    context: dict | None = None


class ResolveAction(BaseModel):
    option_id: str
    payload: dict | None = None


def _filtered(items: list[dict], status: str | None, source: str | None) -> list[dict]:
    if status:
        items = [i for i in items if i.get("status") == status]
    if source:
        items = [i for i in items if i.get("source") == source]
    return items


@router.get("/inbox")
async def list_all_inbox(request: Request, status: str | None = None, source: str | None = None):
    """Aggregate inbox across every registered project (the unified inbox view)."""
    registry = request.app.state.registry
    out: list[dict] = []
    for entry in registry.list():
        items = inbox_store.list_items(Path(entry["root"]))
        out.extend(_filtered(items, status, source))
    out.sort(key=lambda i: i.get("created_at") or "", reverse=True)
    out.sort(key=lambda i: i.get("status") != "pending")
    return out


@router.get("/projects/{project_id}/inbox")
async def list_inbox(request: Request, project_id: str, status: str | None = None,
                     source: str | None = None):
    root = Path(_service(request).get_entry(project_id)["root"])
    return _filtered(inbox_store.list_items(root), status, source)


@router.get("/projects/{project_id}/inbox/{item_id}")
async def get_inbox_item(request: Request, project_id: str, item_id: str):
    root = Path(_service(request).get_entry(project_id)["root"])
    item = inbox_store.read_item(root, item_id)
    if item is None:
        raise ApiError("INBOX_ITEM_NOT_FOUND", f"no inbox item {item_id}", 404)
    return item


@router.post("/projects/{project_id}/inbox")
async def create_inbox_item(request: Request, project_id: str, body: CreateInboxItem):
    root = Path(_service(request).get_entry(project_id)["root"])
    item = {
        "id": inbox_store.new_item_id(),
        "project_id": project_id,
        "source": body.source,
        "kind": body.kind,
        "title": body.title,
        "body": body.body,
        "group_id": body.group_id,
        "group_label": body.group_label,
        "options": [o.model_dump() for o in body.options],
        "context": body.context or {},
        "status": "pending",
        "resolution": None,
        "created_at": _now(),
        "resolved_at": None,
    }
    inbox_store.write_item(root, item)
    request.app.state.bus.publish(
        "sidebar", "inbox_created", {"project_id": project_id, "item": item})
    notifier = getattr(request.app.state, "notifier", None)
    if notifier is not None and notifier.first_in_group(body.group_id):
        notifier.push_bg(
            "Orchid — needs you",
            body.group_label or body.title,
            url=notifier.inbox_url(project_id, item["id"]),
            url_title="Open inbox",
        )
    return item


@router.post("/projects/{project_id}/inbox/{item_id}/resolve")
async def resolve_inbox_item(request: Request, project_id: str, item_id: str, body: ResolveAction):
    root = Path(_service(request).get_entry(project_id)["root"])
    item = inbox_store.read_item(root, item_id)
    if item is None:
        raise ApiError("INBOX_ITEM_NOT_FOUND", f"no inbox item {item_id}", 404)
    options = item.get("options") or []
    if options and not any(o.get("id") == body.option_id for o in options):
        raise ApiError("INVALID_OPTION", f"option {body.option_id!r} not offered", 400)
    item["status"] = "resolved"
    item["resolved_at"] = _now()
    item["resolution"] = {
        "option_id": body.option_id,
        "payload": body.payload or {},
        "resolved_at": item["resolved_at"],
    }
    inbox_store.write_item(root, item)
    request.app.state.bus.publish(
        "sidebar", "inbox_resolved", {"project_id": project_id, "item": item})
    return item


@router.post("/projects/{project_id}/inbox/{item_id}/dismiss")
async def dismiss_inbox_item(request: Request, project_id: str, item_id: str):
    root = Path(_service(request).get_entry(project_id)["root"])
    item = inbox_store.read_item(root, item_id)
    if item is None:
        raise ApiError("INBOX_ITEM_NOT_FOUND", f"no inbox item {item_id}", 404)
    item["status"] = "dismissed"
    item["resolved_at"] = _now()
    inbox_store.write_item(root, item)
    request.app.state.bus.publish(
        "sidebar", "inbox_resolved", {"project_id": project_id, "item": item})
    return item
