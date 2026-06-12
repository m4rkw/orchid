import os
from pathlib import Path
from typing import Any

from claude_agent_sdk import create_sdk_mcp_server, tool

from ..bus import EventBus
from ..config import Settings
from ..services import ApiError, ProjectService
from ..store.paths import canonicalize
from .driver import SessionDriver
from .runner import Runner, RunnerSpec

SYSTEM_PROMPT = """You are Orchid's onboarding assistant. Orchid is a local web UI that manages \
Claude Code sessions across projects. Your single job: help the user register ("onboard") project \
directories so they appear in Orchid's sidebar.

Flow:
1. Ask for the project directory path if you don't have one.
2. Validate it with list_directory; explore with inspect_directory to understand what the project is.
3. Propose a short project name and one-line summary, then ask the user to confirm.
4. Only after explicit confirmation, call register_project. Then tell the user the project is now \
in the sidebar on the left.

Rules:
- Never call register_project without the user's explicit confirmation in this conversation.
- Never invent or guess paths. If a path doesn't exist, say so and ask again.
- Paths may use ~ — the tools expand it.
- Be brief and friendly; plain prose, no headers or bullet lists unless asked.
"""

_SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".orchid", ".next", "target"}
_MANIFESTS = ["pyproject.toml", "package.json", "Cargo.toml", "go.mod", "Gemfile", "composer.json", "Makefile"]


def _text(content: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": content}]}


def _git_info(root: Path) -> str | None:
    head = root / ".git" / "HEAD"
    if not head.is_file():
        return None
    parts = []
    ref = head.read_text().strip()
    if ref.startswith("ref: refs/heads/"):
        parts.append(f"branch {ref.removeprefix('ref: refs/heads/')}")
    config = root / ".git" / "config"
    if config.is_file():
        for line in config.read_text().splitlines():
            line = line.strip()
            if line.startswith("url = "):
                parts.append(f"remote {line.removeprefix('url = ')}")
                break
    return ", ".join(parts) if parts else "git repository"


def _language_histogram(root: Path, cap: int = 2000) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    seen = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")]
        for f in filenames:
            suffix = Path(f).suffix.lower()
            if suffix:
                counts[suffix] = counts.get(suffix, 0) + 1
            seen += 1
            if seen >= cap:
                return sorted(counts.items(), key=lambda kv: -kv[1])[:6]
    return sorted(counts.items(), key=lambda kv: -kv[1])[:6]


def build_onboarding_tools(service: ProjectService, bus: EventBus) -> list[Any]:
    @tool("list_directory", "List the entries of a directory on the user's machine.", {"path": str})
    async def list_directory(args: dict[str, Any]) -> dict[str, Any]:
        try:
            root = canonicalize(args["path"])
            if not root.exists():
                return _text(f"Error: {root} does not exist.")
            if not root.is_dir():
                return _text(f"Error: {root} is not a directory.")
            entries = sorted(root.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
            lines = [f"{root} ({len(entries)} entries)"]
            for p in entries[:200]:
                lines.append(f"  {'d' if p.is_dir() else 'f'} {p.name}")
            if len(entries) > 200:
                lines.append(f"  … {len(entries) - 200} more")
            return _text("\n".join(lines))
        except OSError as exc:
            return _text(f"Error reading directory: {exc}")

    @tool(
        "inspect_directory",
        "Inspect a candidate project directory: README, git info, languages, manifests. Use before proposing a name.",
        {"path": str},
    )
    async def inspect_directory(args: dict[str, Any]) -> dict[str, Any]:
        try:
            root = canonicalize(args["path"])
            if not root.is_dir():
                return _text(f"Error: {root} is not a directory.")
            sections = [f"Inspection of {root}", f"proposed name: {root.name}"]
            git = _git_info(root)
            if git:
                sections.append(git)
            manifests = [m for m in _MANIFESTS if (root / m).is_file()]
            if manifests:
                sections.append("manifests: " + ", ".join(manifests))
            langs = _language_histogram(root)
            if langs:
                sections.append("file types: " + ", ".join(f"{ext}×{n}" for ext, n in langs))
            for name in ("README.md", "README.rst", "README.txt", "README"):
                readme = root / name
                if readme.is_file():
                    head = readme.read_text(errors="replace")[:2000]
                    sections.append(f"--- {name} (first 2000 chars) ---\n{head}")
                    break
            return _text("\n".join(sections))
        except OSError as exc:
            return _text(f"Error inspecting directory: {exc}")

    @tool(
        "register_project",
        "Register a project directory with Orchid so it appears in the sidebar. Call only after the user confirmed.",
        {"path": str, "name": str},
    )
    async def register_project(args: dict[str, Any]) -> dict[str, Any]:
        try:
            project, created = await service.create(args["path"], args.get("name") or None)
        except ApiError as exc:
            return _text(f"Error: {exc.message}")
        bus.publish("onboarding", "project_registered", {"project": project.model_dump()})
        if created:
            return _text(
                f"Registered '{project.name}' at {project.root} "
                f"({project.session_count} existing Claude sessions). It now appears in the sidebar."
            )
        return _text(f"'{project.name}' at {project.root} was already registered — nothing to do.")

    return [list_directory, inspect_directory, register_project]


def build_onboarding_driver(
    runner: Runner, bus: EventBus, service: ProjectService, settings: Settings
) -> SessionDriver:
    server = create_sdk_mcp_server("orchid", "0.1.0", tools=build_onboarding_tools(service, bus))

    def spec_factory(resume_sid: str | None) -> RunnerSpec:
        return RunnerSpec(
            cwd=settings.orchid_home,
            resume=resume_sid,
            system_prompt=SYSTEM_PROMPT,
            mcp_servers={"orchid": server},
            allowed_tools=[
                "Read",
                "Glob",
                "mcp__orchid__list_directory",
                "mcp__orchid__inspect_directory",
                "mcp__orchid__register_project",
            ],
            disallowed_tools=["Bash", "Write", "Edit", "NotebookEdit", "WebFetch", "WebSearch", "Task"],
            permission_mode="bypassPermissions",
        )

    return SessionDriver(runner, spec_factory, bus, topic="onboarding", hold_open=True)
