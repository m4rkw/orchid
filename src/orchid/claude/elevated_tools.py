"""In-process MCP tools for elevated file/exec operations via orchidd.

Same pattern as git_tools.py and planning.py: tools defined here, wired
into sessions via mcp_servers + allowed_tools when the project root is
not owned by the session user and an orchidd ACL grant exists.
"""

from pathlib import Path
from typing import Any

from claude_agent_sdk import create_sdk_mcp_server, tool

from ..orchidd.client import OrchiddClient, OrchiddError

ELEVATED_SERVER = "orchid_elevated"
_TOOLS = [
    "elevated_read_file",
    "elevated_write_file",
    "elevated_edit_file",
    "elevated_delete_file",
    "elevated_mkdir",
    "elevated_chmod",
    "elevated_exec",
    "elevated_stat",
]
ELEVATED_TOOL_NAMES = [f"mcp__{ELEVATED_SERVER}__{t}" for t in _TOOLS]


def _text(s: str, is_error: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {"content": [{"type": "text", "text": s}]}
    if is_error:
        out["is_error"] = True
    return out


def build_elevated_tools(client: OrchiddClient) -> list[Any]:

    @tool(
        "elevated_read_file",
        "Read a root-owned file (elevated via orchidd). Use when regular Read fails "
        "with a permission error. The path must be under an orchidd-granted directory.",
        {"path": str},
    )
    async def elevated_read_file(args: dict[str, Any]) -> dict[str, Any]:
        path = args.get("path", "")
        if not path:
            return _text("path is required", is_error=True)
        try:
            result = await client.read_file("", path)
            return _text(result["content"])
        except OrchiddError as e:
            return _text(f"Error: {e.message}", is_error=True)

    @tool(
        "elevated_write_file",
        "Write a root-owned file (elevated via orchidd). The path must be under an "
        "orchidd-granted directory.",
        {"path": str, "content": str, "mode": str},
    )
    async def elevated_write_file(args: dict[str, Any]) -> dict[str, Any]:
        path = args.get("path", "")
        content = args.get("content", "")
        if not path:
            return _text("path is required", is_error=True)
        try:
            mode = args.get("mode") or None
            result = await client.write_file("", path, content, mode)
            return _text(f"Wrote {result['bytes_written']} bytes to {result['path']}.")
        except OrchiddError as e:
            return _text(f"Error: {e.message}", is_error=True)

    @tool(
        "elevated_edit_file",
        "Edit a root-owned file (elevated via orchidd). Replaces one occurrence of "
        "old_text with new_text. Path must be under an orchidd-granted directory.",
        {"path": str, "old_text": str, "new_text": str},
    )
    async def elevated_edit_file(args: dict[str, Any]) -> dict[str, Any]:
        path = args.get("path", "")
        old_text = args.get("old_text", "")
        new_text = args.get("new_text", "")
        if not path or not old_text:
            return _text("path and old_text are required", is_error=True)
        try:
            result = await client.edit_file("", path, old_text, new_text)
            mode = result.get("mode")
            suffix = f" (mode {mode} preserved)" if mode else ""
            return _text(f"Edited {result['path']}{suffix}.")
        except OrchiddError as e:
            return _text(f"Error: {e.message}", is_error=True)

    @tool(
        "elevated_delete_file",
        "Delete a root-owned file (elevated via orchidd). Path must be under an "
        "orchidd-granted directory.",
        {"path": str},
    )
    async def elevated_delete_file(args: dict[str, Any]) -> dict[str, Any]:
        path = args.get("path", "")
        if not path:
            return _text("path is required", is_error=True)
        try:
            result = await client.delete_file("", path)
            return _text(f"Deleted {result['path']}.")
        except OrchiddError as e:
            return _text(f"Error: {e.message}", is_error=True)

    @tool(
        "elevated_mkdir",
        "Create a directory with elevated privileges (via orchidd). Path must be "
        "under an orchidd-granted directory.",
        {"path": str},
    )
    async def elevated_mkdir(args: dict[str, Any]) -> dict[str, Any]:
        path = args.get("path", "")
        if not path:
            return _text("path is required", is_error=True)
        try:
            result = await client.mkdir("", path)
            return _text(f"Created {result['path']}.")
        except OrchiddError as e:
            return _text(f"Error: {e.message}", is_error=True)

    @tool(
        "elevated_chmod",
        "Set the permission bits of a root-owned path (elevated via orchidd) WITHOUT rewriting "
        "its contents — use this to fix a mode (e.g. restore an executable bit) instead of "
        "re-sending a whole file. mode is octal like '0755'. Path must be under an "
        "orchidd-granted directory.",
        {"path": str, "mode": str},
    )
    async def elevated_chmod(args: dict[str, Any]) -> dict[str, Any]:
        path = args.get("path", "")
        mode = args.get("mode", "")
        if not path or not mode:
            return _text("path and mode are required", is_error=True)
        try:
            result = await client.chmod("", path, mode)
            return _text(f"Set mode {result['mode']} on {result['path']}.")
        except OrchiddError as e:
            return _text(f"Error: {e.message}", is_error=True)

    @tool(
        "elevated_exec",
        "Run a whitelisted command with elevated privileges (via orchidd). Only "
        "commands explicitly allowed in the orchidd ACL will succeed.",
        {"command": str},
    )
    async def elevated_exec(args: dict[str, Any]) -> dict[str, Any]:
        command = args.get("command", "")
        if not command:
            return _text("command is required", is_error=True)
        try:
            result = await client.exec("", command)
            parts = []
            if result.get("stdout"):
                parts.append(result["stdout"])
            if result.get("stderr"):
                parts.append(f"stderr:\n{result['stderr']}")
            parts.append(f"exit code: {result['exit_code']}")
            return _text("\n".join(parts))
        except OrchiddError as e:
            return _text(f"Error: {e.message}", is_error=True)

    @tool(
        "elevated_stat",
        "Get file metadata (owner, mode, size) for a path under an orchidd-granted directory.",
        {"path": str},
    )
    async def elevated_stat(args: dict[str, Any]) -> dict[str, Any]:
        path = args.get("path", "")
        if not path:
            return _text("path is required", is_error=True)
        try:
            result = await client.stat("", path)
            lines = [
                f"path: {result['path']}",
                f"type: {'directory' if result['is_dir'] else 'file'}",
                f"size: {result['size']}",
                f"mode: {result['mode']}",
                f"owner: {result['owner']}:{result['group']}",
            ]
            return _text("\n".join(lines))
        except OrchiddError as e:
            return _text(f"Error: {e.message}", is_error=True)

    return [
        elevated_read_file, elevated_write_file, elevated_edit_file,
        elevated_delete_file, elevated_mkdir, elevated_chmod, elevated_exec, elevated_stat,
    ]


def build_elevated_server(client: OrchiddClient) -> Any:
    return create_sdk_mcp_server(
        ELEVATED_SERVER, "0.1.0",
        tools=build_elevated_tools(client),
    )
