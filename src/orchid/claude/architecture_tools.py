"""In-process MCP tools to read and update the project's living architecture
definition (.orchid/architecture.json). Same pattern as spec_tools.py.

The architecture is the foundational living document: it describes how the
system is built (structure, components, boundaries, key decisions) and PRECEDES
and INFORMS the specification. Agents verify their work against it and keep it
current; the spec must remain consistent with it. One document per project.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from claude_agent_sdk import create_sdk_mcp_server, tool

from ..bus import EventBus
from ..store import architecture_store

ARCH_SERVER = "orchid_architecture"
_TOOLS = ["get_architecture", "update_architecture"]
ARCH_TOOL_NAMES = [f"mcp__{ARCH_SERVER}__{t}" for t in _TOOLS]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(s: str, is_error: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {"content": [{"type": "text", "text": s}]}
    if is_error:
        out["is_error"] = True
    return out


def build_architecture_tools(root: Path, project_id: str, bus: EventBus) -> list[Any]:

    def _save_and_emit(arch: dict[str, Any]) -> None:
        arch["updated_at"] = _now()
        architecture_store.write_architecture(root, arch)
        bus.publish("sidebar", "architecture_updated", {"project_id": project_id, "architecture": arch})

    @tool("get_architecture",
          "Read the project's living architecture definition (how the system is built). "
          "This is the foundation the spec is derived from — read it before changing structure. "
          "Returns the full architecture content or a message if none exists yet.", {})
    async def get_architecture(_args: dict[str, Any]) -> dict[str, Any]:
        arch = architecture_store.read_architecture(root)
        if arch is None:
            return _text("No architecture definition exists for this project yet.")
        return _text(f"# {arch.get('title', 'Architecture')}\n\n{arch['content']}")

    @tool("update_architecture",
          "Update the project's living architecture definition. The architecture precedes and "
          "informs the spec, so any structural change — new components, moved boundaries, changed "
          "data flow or dependencies — MUST be reflected here, and the spec kept consistent with "
          "it. Provide the full updated content (markdown). Use `section` to replace one section "
          "by heading.",
          {"title": str, "content": str, "section": str})
    async def update_architecture(args: dict[str, Any]) -> dict[str, Any]:
        content = (args.get("content") or "").strip()
        if not content:
            return _text("Content is required.", is_error=True)
        existing = architecture_store.read_architecture(root)
        now = _now()
        section = (args.get("section") or "").strip()
        if section and existing:
            existing_content = existing.get("content", "")
            updated = _replace_section(existing_content, section, content)
            if updated is None:
                return _text(f"Section '{section}' not found in the architecture. "
                             "Provide full content or use an existing heading.", is_error=True)
            content = updated
        if existing:
            existing["content"] = content
            existing["version"] = existing.get("version", 0) + 1
            if args.get("title"):
                existing["title"] = args["title"]
            _save_and_emit(existing)
            return _text(f"Architecture updated (v{existing['version']}).")
        arch = {
            "version": 1,
            "title": args.get("title") or "Architecture",
            "content": content,
            "status": "active",
            "created_at": now,
            "updated_at": now,
        }
        _save_and_emit(arch)
        return _text("Architecture created (v1).")

    return [get_architecture, update_architecture]


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


def build_architecture_server(root: Path, project_id: str, bus: EventBus) -> Any:
    return create_sdk_mcp_server(
        ARCH_SERVER, "0.1.0", tools=build_architecture_tools(root, project_id, bus),
    )
