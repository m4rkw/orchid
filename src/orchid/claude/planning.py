"""In-process MCP tools that let the orchestrator session persist its plan to
<root>/.orchid/plans/. Same pattern as onboarding's tools: defined here (under
claude/), wired into the session via mcp_servers + allowed_tools, and each
mutation publishes a `plan_upserted` event so the web UI updates live.

A plan on disk is what makes the planner durable — the orchestrator can re-read
it after its context window rolls over and pick up exactly where it left off.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from claude_agent_sdk import create_sdk_mcp_server, tool

from ..bus import EventBus
from ..store import plan_store

PLAN_SERVER = "orchid_plan"
_TOOLS = ["create_plan", "add_step", "update_step", "set_plan_status", "list_plans", "get_plan"]
# Pre-approved on the orchestrator session so plan bookkeeping never prompts.
PLAN_TOOL_NAMES = [f"mcp__{PLAN_SERVER}__{t}" for t in _TOOLS]

_STEP_STATUS = {"pending", "in_progress", "done", "blocked"}
_PLAN_STATUS = {"active", "done", "abandoned"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(s: str, is_error: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {"content": [{"type": "text", "text": s}]}
    if is_error:
        out["is_error"] = True
    return out


def _roles(raw: str) -> list[str]:
    return [r.strip() for r in (raw or "").replace(",", "\n").splitlines() if r.strip()]


def _render(plan: dict[str, Any]) -> str:
    lines = [f"{plan['id']} — \"{plan['title']}\" [{plan.get('status', 'active')}]"]
    if plan.get("goal"):
        lines.append(f"goal: {plan['goal']}")
    steps = plan.get("steps") or []
    if not steps:
        lines.append("(no steps yet — add some with add_step)")
    for i, st in enumerate(steps, 1):
        roles = f"  (roles: {', '.join(st['roles'])})" if st.get("roles") else ""
        note = f"  — {st['notes']}" if st.get("notes") else ""
        lines.append(f"  {i}. [{st.get('status', 'pending')}] {st['id']} — {st['title']}{roles}{note}")
    return "\n".join(lines)


def build_plan_tools(root: Path, project_id: str, bus: EventBus) -> list[Any]:
    def _save_and_emit(plan: dict[str, Any]) -> None:
        plan["updated_at"] = _now()
        plan_store.write_plan(root, plan)
        bus.publish("sidebar", "plan_upserted", {"project_id": project_id, "plan": plan})

    def _load(plan_id: str) -> dict[str, Any] | None:
        return plan_store.read_plan(root, plan_id)

    @tool("create_plan", "Create a new plan. `steps` is optional: one step title per line.",
          {"title": str, "goal": str, "steps": str})
    async def create_plan(args: dict[str, Any]) -> dict[str, Any]:
        now = _now()
        steps = [
            {"id": plan_store.new_step_id(), "title": t.strip(), "status": "pending", "roles": [], "notes": None}
            for t in (args.get("steps") or "").splitlines()
            if t.strip()
        ]
        plan = {
            "version": 1,
            "id": plan_store.new_plan_id(),
            "title": args.get("title") or "Untitled plan",
            "goal": args.get("goal") or "",
            "status": "active",
            "steps": steps,
            "created_at": now,
            "updated_at": now,
        }
        _save_and_emit(plan)
        return _text("Created plan.\n" + _render(plan))

    @tool("add_step", "Add a step to a plan. `roles` is an optional comma-separated list of role slugs.",
          {"plan_id": str, "title": str, "roles": str})
    async def add_step(args: dict[str, Any]) -> dict[str, Any]:
        plan = _load(args.get("plan_id", ""))
        if plan is None:
            return _text(f"No plan {args.get('plan_id')!r}.", is_error=True)
        step = {
            "id": plan_store.new_step_id(),
            "title": args.get("title") or "Untitled step",
            "status": "pending",
            "roles": _roles(args.get("roles", "")),
            "notes": None,
        }
        plan["steps"].append(step)
        _save_and_emit(plan)
        return _text(f"Added step {step['id']}.\n" + _render(plan))

    @tool("update_step", "Update a step. Provide only the fields to change: status "
          "(pending|in_progress|done|blocked), notes, roles (comma-separated).",
          {"plan_id": str, "step_id": str, "status": str, "notes": str, "roles": str})
    async def update_step(args: dict[str, Any]) -> dict[str, Any]:
        plan = _load(args.get("plan_id", ""))
        if plan is None:
            return _text(f"No plan {args.get('plan_id')!r}.", is_error=True)
        step = next((s for s in plan["steps"] if s["id"] == args.get("step_id")), None)
        if step is None:
            return _text(f"No step {args.get('step_id')!r} in {plan['id']}.", is_error=True)
        status = (args.get("status") or "").strip()
        if status:
            if status not in _STEP_STATUS:
                return _text(f"Invalid status {status!r}; use {sorted(_STEP_STATUS)}.", is_error=True)
            step["status"] = status
        if args.get("notes"):
            step["notes"] = args["notes"]
        if args.get("roles"):
            step["roles"] = _roles(args["roles"])
        _save_and_emit(plan)
        return _text(_render(plan))

    @tool("set_plan_status", "Set a plan's overall status (active|done|abandoned).",
          {"plan_id": str, "status": str})
    async def set_plan_status(args: dict[str, Any]) -> dict[str, Any]:
        plan = _load(args.get("plan_id", ""))
        if plan is None:
            return _text(f"No plan {args.get('plan_id')!r}.", is_error=True)
        status = (args.get("status") or "").strip()
        if status not in _PLAN_STATUS:
            return _text(f"Invalid status {status!r}; use {sorted(_PLAN_STATUS)}.", is_error=True)
        plan["status"] = status
        _save_and_emit(plan)
        return _text(_render(plan))

    @tool("list_plans", "List this project's plans.", {})
    async def list_plans(_args: dict[str, Any]) -> dict[str, Any]:
        plans = plan_store.list_plans(root)
        if not plans:
            return _text("No plans yet. Create one with create_plan.")
        lines = []
        for p in plans:
            done = sum(1 for s in p.get("steps", []) if s.get("status") == "done")
            lines.append(f"{p['id']} — \"{p['title']}\" [{p.get('status', 'active')}] {done}/{len(p.get('steps', []))} steps")
        return _text("\n".join(lines))

    @tool("get_plan", "Show a plan in full.", {"plan_id": str})
    async def get_plan(args: dict[str, Any]) -> dict[str, Any]:
        plan = _load(args.get("plan_id", ""))
        if plan is None:
            return _text(f"No plan {args.get('plan_id')!r}.", is_error=True)
        return _text(_render(plan))

    return [create_plan, add_step, update_step, set_plan_status, list_plans, get_plan]


def build_plan_server(root: Path, project_id: str, bus: EventBus) -> Any:
    return create_sdk_mcp_server(PLAN_SERVER, "0.1.0", tools=build_plan_tools(root, project_id, bus))
