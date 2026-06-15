"""In-process MCP tools that let the orchestrator read and update the project's
living specification (.orchid/spec.json). Same pattern as planning.py: tools
defined here, wired via mcp_servers + allowed_tools, mutations publish events.

The spec is the canonical reference for what the project should do — agents
verify their work against it. It is a single document per project.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from claude_agent_sdk import create_sdk_mcp_server, tool

from ..bus import EventBus
from ..store import spec_store

SPEC_SERVER = "orchid_spec"
_TOOLS = ["get_spec", "update_spec"]
SPEC_TOOL_NAMES = [f"mcp__{SPEC_SERVER}__{t}" for t in _TOOLS]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(s: str, is_error: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {"content": [{"type": "text", "text": s}]}
    if is_error:
        out["is_error"] = True
    return out


def build_spec_tools(root: Path, project_id: str, bus: EventBus) -> list[Any]:

    def _save_and_emit(spec: dict[str, Any]) -> None:
        spec["updated_at"] = _now()
        spec_store.write_spec(root, spec)
        bus.publish("sidebar", "spec_updated", {"project_id": project_id, "spec": spec})

    @tool("get_spec",
          "Read the project's living specification. Returns the full spec content "
          "or a message if none exists yet.", {})
    async def get_spec(_args: dict[str, Any]) -> dict[str, Any]:
        spec = spec_store.read_spec(root)
        if spec is None:
            return _text("No specification exists for this project yet.")
        return _text(f"# {spec.get('title', 'Specification')}\n\n{spec['content']}")

    @tool("update_spec",
          "Update the project's living specification. Any change to project behaviour, "
          "features, or requirements MUST be reflected here. Provide the full updated "
          "content (markdown). Use `section` to replace only one section by heading.",
          {"title": str, "content": str, "section": str})
    async def update_spec(args: dict[str, Any]) -> dict[str, Any]:
        content = (args.get("content") or "").strip()
        if not content:
            return _text("Content is required.", is_error=True)
        existing = spec_store.read_spec(root)
        now = _now()
        section = (args.get("section") or "").strip()
        if section and existing:
            existing_content = existing.get("content", "")
            updated = _replace_section(existing_content, section, content)
            if updated is None:
                return _text(f"Section '{section}' not found in the spec. "
                             "Provide full content or use an existing heading.", is_error=True)
            content = updated
        if existing:
            existing["content"] = content
            existing["version"] = existing.get("version", 0) + 1
            if args.get("title"):
                existing["title"] = args["title"]
            _save_and_emit(existing)
            return _text(f"Spec updated (v{existing['version']}).")
        spec = {
            "version": 1,
            "title": args.get("title") or "Specification",
            "content": content,
            "status": "active",
            "created_at": now,
            "updated_at": now,
        }
        _save_and_emit(spec)
        return _text("Spec created (v1).")

    return [get_spec, update_spec]


def _replace_section(full: str, heading: str, new_content: str) -> str | None:
    """Replace a markdown section (identified by heading text) with new_content."""
    lines = full.split("\n")
    start = None
    level = None
    for i, line in enumerate(lines):
        stripped = line.lstrip("#")
        hashes = len(line) - len(stripped)
        if hashes > 0 and stripped.strip().lower() == heading.lower():
            start = i
            level = hashes
            break
    if start is None:
        return None
    end = len(lines)
    for i in range(start + 1, len(lines)):
        stripped = lines[i].lstrip("#")
        hashes = len(lines[i]) - len(stripped)
        if hashes > 0 and hashes <= level and stripped.strip():
            end = i
            break
    prefix = "#" * level
    replaced = lines[:start] + [f"{prefix} {heading}", "", new_content.strip(), ""] + lines[end:]
    return "\n".join(replaced).strip()


def build_spec_server(root: Path, project_id: str, bus: EventBus) -> Any:
    return create_sdk_mcp_server(
        SPEC_SERVER, "0.1.0", tools=build_spec_tools(root, project_id, bus),
    )
