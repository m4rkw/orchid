"""In-process MCP tools that let an orchestrator consult another project's
active session.  Same pattern as planning.py / git_tools.py: tools defined
here, wired via mcp_servers + allowed_tools, and the tool blocks the caller
while the consulted session runs to completion.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, TYPE_CHECKING

from claude_agent_sdk import create_sdk_mcp_server, tool

from ..bus import EventBus
from ..store import project_store

if TYPE_CHECKING:
    from .driver_manager import DriverManager
    from ..store.registry import Registry

log = logging.getLogger(__name__)

CONSULT_SERVER = "orchid_consult"
_TOOLS = ["consult", "list_active_projects"]
CONSULT_TOOL_NAMES = [f"mcp__{CONSULT_SERVER}__{t}" for t in _TOOLS]

DEFAULT_TIMEOUT_S = 300
MAX_RESPONSE_CHARS = 100_000


def _text(s: str, is_error: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {"content": [{"type": "text", "text": s}]}
    if is_error:
        out["is_error"] = True
    return out


def _resolve_project(registry: Registry, name_or_id: str) -> dict | None:
    entries = registry.list()
    for e in entries:
        if e["id"] == name_or_id:
            return e
    needle = name_or_id.strip().lower()
    for e in entries:
        pf = project_store.read_project_file(Path(e["root"]))
        if pf and pf.get("name", "").strip().lower() == needle:
            return e
    return None


async def _collect_response(
    bus: EventBus, target_sid: str, timeout_s: float,
) -> str:
    """Subscribe, wait for the turn our prompt triggers, collect assistant text."""
    sub = bus.subscribe({f"session:{target_sid}"})
    texts: list[str] = []
    total_chars = 0
    saw_turn_start = False
    try:
        deadline = asyncio.get_event_loop().time() + timeout_s
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                raise asyncio.TimeoutError()
            if sub.dead.is_set():
                texts.append("\n\n[Bus subscriber overflowed — response lost]")
                break
            envelope = await asyncio.wait_for(sub.queue.get(), timeout=remaining)
            etype = envelope["type"]
            if etype == "turn_started":
                saw_turn_start = True
                texts.clear()
                total_chars = 0
            elif etype == "message" and saw_turn_start:
                msg = envelope["payload"].get("message", {})
                if msg.get("role") == "assistant":
                    for block in msg.get("blocks", []):
                        if block.get("type") == "text" and block.get("text"):
                            t = block["text"]
                            room = MAX_RESPONSE_CHARS - total_chars
                            if room <= 0:
                                continue
                            if len(t) > room:
                                t = t[:room]
                                texts.append(t)
                                texts.append("\n\n[Response truncated at 100k chars]")
                                total_chars = MAX_RESPONSE_CHARS
                            else:
                                texts.append(t)
                                total_chars += len(t)
            elif etype == "turn_completed" and saw_turn_start:
                break
            elif etype == "error" and saw_turn_start:
                texts.append(
                    f"\n\n[Error in consulted session: "
                    f"{envelope['payload'].get('message', 'unknown')}]"
                )
                break
    except asyncio.TimeoutError:
        texts.append(f"\n\n[Consultation timed out after {timeout_s}s]")
    finally:
        bus.unsubscribe(sub)
    return "\n\n".join(texts) if texts else "(no response text)"


def build_consult_tools(
    dm: DriverManager,
    registry: Registry,
    bus: EventBus,
    caller_holder: dict,
) -> list[Any]:

    @tool(
        "consult",
        "Send a message to another project's active session and wait for its response. "
        "Use this to ask another project's agent for help, coordinate cross-project work, "
        "or report issues. The target project must have an active or idle Orchid session.",
        {"project": str, "message": str, "timeout": str},
    )
    async def consult(args: dict[str, Any]) -> dict[str, Any]:
        project_ref = (args.get("project") or "").strip()
        message = (args.get("message") or "").strip()
        if not project_ref:
            return _text("'project' is required (project name or id).", is_error=True)
        if not message:
            return _text("'message' is required.", is_error=True)

        try:
            timeout_s = float(args.get("timeout") or DEFAULT_TIMEOUT_S)
        except (ValueError, TypeError):
            timeout_s = DEFAULT_TIMEOUT_S
        timeout_s = min(max(timeout_s, 10), 600)

        entry = _resolve_project(registry, project_ref)
        if entry is None:
            return _text(
                f"No project matching '{project_ref}'. "
                "Use list_active_projects to see available projects.",
                is_error=True,
            )

        project_id = entry["id"]
        pf = project_store.read_project_file(Path(entry["root"])) or {}
        project_name = pf.get("name", project_id)

        target_sid = _find_target(dm, project_id)
        if target_sid is None:
            return _text(
                f"No session in project '{project_name}'. "
                "Start a session there first, then consult it.",
                is_error=True,
            )

        caller = caller_holder.get("driver")
        if caller and caller.session_id == target_sid:
            return _text("Cannot consult your own session.", is_error=True)

        caller_sid = caller.session_id if caller else None
        if caller_sid:
            bus.publish(
                f"session:{caller_sid}",
                "consult_started",
                {"target_project": project_name, "target_session": target_sid,
                 "message_preview": message[:200]},
            )

        # Subscribe BEFORE sending the prompt so we never miss early events.
        sub = bus.subscribe({f"session:{target_sid}"})
        try:
            await dm.prompt(target_sid, message, force=True)
        except Exception as exc:
            bus.unsubscribe(sub)
            return _text(f"Failed to send prompt to '{project_name}': {exc}", is_error=True)

        texts: list[str] = []
        total_chars = 0
        saw_turn_start = False
        try:
            deadline = asyncio.get_event_loop().time() + timeout_s
            while True:
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    raise asyncio.TimeoutError()
                if sub.dead.is_set():
                    texts.append("\n\n[Bus subscriber overflowed — response lost]")
                    break
                envelope = await asyncio.wait_for(sub.queue.get(), timeout=remaining)
                etype = envelope["type"]
                if etype == "turn_started":
                    saw_turn_start = True
                    texts.clear()
                    total_chars = 0
                elif etype == "message" and saw_turn_start:
                    msg = envelope["payload"].get("message", {})
                    if msg.get("role") == "assistant":
                        for block in msg.get("blocks", []):
                            if block.get("type") == "text" and block.get("text"):
                                t = block["text"]
                                room = MAX_RESPONSE_CHARS - total_chars
                                if room <= 0:
                                    continue
                                if len(t) > room:
                                    t = t[:room]
                                    texts.append(t)
                                    texts.append("\n\n[Response truncated at 100k chars]")
                                    total_chars = MAX_RESPONSE_CHARS
                                else:
                                    texts.append(t)
                                    total_chars += len(t)
                elif etype == "turn_completed" and saw_turn_start:
                    break
                elif etype == "error" and saw_turn_start:
                    texts.append(
                        f"\n\n[Error in consulted session: "
                        f"{envelope['payload'].get('message', 'unknown')}]"
                    )
                    break
        except asyncio.TimeoutError:
            texts.append(f"\n\n[Consultation timed out after {timeout_s}s]")
        finally:
            bus.unsubscribe(sub)

        response = "\n\n".join(texts) if texts else "(no response text)"

        if caller_sid:
            bus.publish(
                f"session:{caller_sid}",
                "consult_completed",
                {"target_project": project_name, "target_session": target_sid},
            )

        return _text(f"Response from {project_name}:\n\n{response}")

    @tool(
        "list_active_projects",
        "List all registered projects and whether they have sessions that can be consulted.",
        {},
    )
    async def list_active_projects(_args: dict[str, Any]) -> dict[str, Any]:
        entries = registry.list()
        all_drivers = dm.all_active_projects()
        lines = []
        for e in entries:
            pid = e["id"]
            root = Path(e["root"])
            pf = project_store.read_project_file(root)
            name = pf.get("name", root.name) if pf else root.name
            sids = all_drivers.get(pid, [])
            if sids:
                lines.append(f"  {name} ({pid}) — {len(sids)} session(s)")
            else:
                lines.append(f"  {name} ({pid}) — no session")
        if not lines:
            return _text("No projects registered.")
        return _text("Projects:\n" + "\n".join(lines))

    return [consult, list_active_projects]


def _find_target(dm: DriverManager, project_id: str) -> str | None:
    """Find the best session to consult: prefer running, fall back to idle with a driver."""
    running = dm.active_sessions_for_project(project_id)
    if running:
        return running[0]
    for sid, pid in dm._projects_of.items():
        if pid == project_id and sid in dm._drivers:
            return sid
    return None


def build_consult_server(
    dm: DriverManager,
    registry: Registry,
    bus: EventBus,
    caller_holder: dict,
) -> Any:
    return create_sdk_mcp_server(
        CONSULT_SERVER, "0.1.0",
        tools=build_consult_tools(dm, registry, bus, caller_holder),
    )
