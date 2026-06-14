import asyncio
import os
import uuid
from pathlib import Path
from typing import Any

from claude_agent_sdk import create_sdk_mcp_server, tool

from ..bus import EventBus
from ..config import Settings
from ..services import ApiError, ProjectService
from ..store import agents_store, project_store
from ..store.paths import canonicalize
from . import roles
from .driver import SessionDriver
from .runner import Runner, RunnerSpec

SYSTEM_PROMPT = """You are the Orchid console — the management interface for Orchid, a local web UI \
that manages Claude Code sessions across projects. You help the user with anything across their \
projects: onboarding new ones, creating projects from scratch, checking status, managing settings, \
or answering questions.

When onboarding an existing project:
1. Ask for the project directory path if you don't have one. Validate it with list_directory.
2. Analyse the project: use inspect_directory, then Read/Glob the README, manifests, and a couple \
of entry points to understand what it is, its layout, and how to build/test/run it.
3. Summarise what you found in a sentence or two, then propose (a) a short project name and (b) an \
AGENTS.md: a concise project memory with a one-paragraph summary, the key layout, build/test/run \
commands, important conventions/gotchas, and a short "Agent roles" note. Show the proposed \
AGENTS.md and ask the user to confirm or correct it.
4. Incorporate any corrections the user makes and re-show it.
5. Only after explicit confirmation: call register_project, then write_agents_md with the agreed \
content, then assign_roles (default: orchestrator, worker, reviewer, verifier — unless the user \
wants different).
6. Check for a .git directory. If missing, offer to initialise one with git_init — Orchid's branch \
workflow requires git.
7. Ask about their intent — call ask_choice(question, "Ad-hoc changes,Working towards a goal"):
   - "Ad-hoc changes" — using sessions for quick, unrelated tasks; no overarching goal
   - "Working towards a goal" — there's a specific end state in mind
   If they pick the goal, ask them to describe it in a sentence or two (free text — no ask_choice).
8. Ask about review mode — call ask_choice(question, "Manual review,Fully autonomous"):
   - "Manual review" — they review branches and approve merges themselves
   - "Fully autonomous" — a reviewer agent automatically reviews and approves changes
9. Store with set_project_intent. Summarise: "Project set up. Intent: <x>, review: <y>."

When creating a project from scratch:
1. Ask what they want to build — gather enough to pick a language/framework and structure.
2. Use scaffold_project to create the directory, init git, and register it.
3. Continue from step 3 of the onboarding flow (AGENTS.md, roles, intent, review mode).

When creating a meta-project:
A meta-project orchestrates work across multiple child repositories — e.g. a platform with a \
web UI + backend services + shared libraries. It has its own directory (for plans and the \
orchestrator's context) but the real code lives in the children.
1. Ask what the system/platform comprises and where each repo lives.
2. Use scaffold_project with project_type="meta" for the meta-project root.
3. Register each child repo if not already onboarded (inspect, AGENTS.md, register as usual).
4. Use add_child_project to link each child under the meta-project.
5. Write the meta-project's own AGENTS.md: a high-level system overview, what each child does, \
how they relate, shared conventions, and cross-repo concerns.
6. Set up roles and intent on the meta-project as usual.
The meta-project's orchestrator automatically gets AGENTS.md from all children injected into \
its context, so it has full cross-project awareness.

The roles: orchestrator (plans + delegates), worker (implements), reviewer (critiques), verifier \
(runs tests). Router/retriever/memory/tool-action are intentionally off — Orchid's permission \
broker and the model already cover them. The user can change roles later in project settings.

For general questions: answer from what you know about Orchid and the user's registered projects. \
You can inspect project directories with list_directory and inspect_directory.

Rules:
- Whenever a question has a small fixed set of answers (intent, review mode, yes/no choices like \
git init), call ask_choice to render them as one-click buttons — and still phrase the question in \
your reply text so it reads naturally and works without the buttons. Ask one such question per call.
- Never register, write AGENTS.md, or assign roles without the user's explicit confirmation.
- Never invent or guess paths. If a path doesn't exist, say so and ask again.
- Keep AGENTS.md concise and accurate — only state build/test commands you saw evidence for \
(a manifest or README), never guesses.
- Paths may use ~ — the tools expand it.
- Be brief and friendly; plain prose.
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
                f"Registered '{project.name}' at {project.root}. It now appears in the sidebar — "
                f"start a session there and Orchid will manage it. (Any sessions you started in a "
                f"terminal stay yours; Orchid won't touch them.)"
            )
        return _text(f"'{project.name}' at {project.root} was already registered — nothing to do.")

    @tool(
        "write_agents_md",
        "Write (or overwrite) the project's AGENTS.md — the project memory Orchid loads into "
        "every agent session. Call only after the user has approved the content.",
        {"path": str, "content": str},
    )
    async def write_agents_md(args: dict[str, Any]) -> dict[str, Any]:
        try:
            root = canonicalize(args["path"])
            if not root.is_dir():
                return _text(f"Error: {root} is not a directory.")
            content = args.get("content") or ""
            (root / "AGENTS.md").write_text(content if content.endswith("\n") else content + "\n")
        except OSError as exc:
            return _text(f"Error writing AGENTS.md: {exc}")
        bus.publish("onboarding", "agents_md_written", {"path": str(root / "AGENTS.md")})
        return _text(f"Wrote {root / 'AGENTS.md'} ({len(content)} chars).")

    @tool(
        "assign_roles",
        "Set which agent roles are enabled for the project. `enabled` is a comma-separated list "
        "of role slugs. Materialized roles: orchestrator, worker, reviewer, verifier. The rest "
        "(router, retriever, memory, tool_action) are covered by Orchid/the model and off by default.",
        {"path": str, "enabled": str},
    )
    async def assign_roles(args: dict[str, Any]) -> dict[str, Any]:
        try:
            root = canonicalize(args["path"])
            if not root.is_dir():
                return _text(f"Error: {root} is not a directory.")
            wanted = {s.strip() for s in (args.get("enabled") or "").replace(",", "\n").splitlines() if s.strip()}
            payload = [{"slug": r.slug, "enabled": r.slug in wanted} for r in roles.BUILTIN_ROLES]
            agents_store.write_agent_overrides(root, roles.normalize_overrides(payload))
        except OSError as exc:
            return _text(f"Error assigning roles: {exc}")
        enabled_now = [r.slug for r in roles.resolve_roles(root) if r.enabled]
        bus.publish("onboarding", "roles_assigned", {"path": str(root), "enabled": enabled_now})
        return _text(f"Enabled roles: {', '.join(enabled_now) or '(none)'}.")

    @tool(
        "git_init",
        "Initialize a git repository in the given directory. Use if the project has no .git.",
        {"path": str},
    )
    async def git_init(args: dict[str, Any]) -> dict[str, Any]:
        try:
            root = canonicalize(args["path"])
            if not root.is_dir():
                return _text(f"Error: {root} is not a directory.")
            if (root / ".git").exists():
                return _text(f"{root} already has a .git — nothing to do.")
            proc = await asyncio.create_subprocess_exec(
                "git", "init", cwd=str(root),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            )
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            if proc.returncode != 0:
                return _text(f"git init failed:\n{out.decode()}")
            return _text(f"Initialized git repository in {root}.")
        except (OSError, asyncio.TimeoutError) as exc:
            return _text(f"Error: {exc}")

    @tool(
        "ask_choice",
        "Ask the user a question that has a small fixed set of answers; the web UI renders the "
        "options as one-click buttons. `options` is a comma-separated list of short answer labels "
        "(e.g. 'Ad-hoc changes,Working towards a goal'). The chosen label arrives as the user's "
        "next message. Also phrase the question in your reply text. Ask one question per call.",
        {"question": str, "options": str},
    )
    async def ask_choice(args: dict[str, Any]) -> dict[str, Any]:
        question = (args.get("question") or "").strip()
        options = [o.strip() for o in (args.get("options") or "").split(",") if o.strip()]
        if not question or not options:
            return _text("Error: ask_choice needs a question and at least one comma-separated option.")
        bus.publish(
            "onboarding",
            "choice_prompt",
            {"id": uuid.uuid4().hex, "question": question, "options": options},
        )
        return _text(
            f"Showed the user quick-reply buttons: {', '.join(options)}. "
            f"Wait for their selection — it arrives as their next message."
        )

    @tool(
        "set_project_intent",
        "Set the project's working mode after onboarding. intent='adhoc' or 'goal'; "
        "goal=text (required if goal); review_mode='manual' or 'autonomous'.",
        {"path": str, "intent": str, "goal": str, "review_mode": str},
    )
    async def set_project_intent(args: dict[str, Any]) -> dict[str, Any]:
        try:
            root = canonicalize(args["path"])
            intent = (args.get("intent") or "").strip()
            if intent not in ("adhoc", "goal"):
                return _text(f"Error: intent must be 'adhoc' or 'goal', got {intent!r}.")
            review_mode = (args.get("review_mode") or "").strip()
            if review_mode not in ("manual", "autonomous"):
                return _text(f"Error: review_mode must be 'manual' or 'autonomous', got {review_mode!r}.")
            goal_text = (args.get("goal") or "").strip() or None
            file = project_store.read_project_file(root)
            if file is None:
                return _text("Error: project not registered yet (register_project first).")
            file["intent"] = intent
            file["goal"] = goal_text if intent == "goal" else None
            file["review_mode"] = review_mode
            project_store.write_project_file(root, file)
            entry = service._registry.find_by_root(root)
            if entry:
                project = await service._to_project(entry)
                bus.publish("sidebar", "project_updated", {"project": project.model_dump()})
            return _text(f"Set intent={intent}, goal={goal_text!r}, review_mode={review_mode}.")
        except OSError as exc:
            return _text(f"Error: {exc}")

    @tool(
        "scaffold_project",
        "Create a new project directory, init git, and register it with Orchid. "
        "Use for brand-new projects or meta-project roots.",
        {"path": str, "name": str, "project_type": str},
    )
    async def scaffold_project(args: dict[str, Any]) -> dict[str, Any]:
        try:
            raw = args["path"].strip()
            if raw.startswith("~"):
                raw = str(Path(raw).expanduser())
            target = canonicalize(raw)
            if target.exists() and any(target.iterdir()):
                return _text(f"Error: {target} already exists and is not empty.")
            target.mkdir(parents=True, exist_ok=True)
            proc = await asyncio.create_subprocess_exec(
                "git", "init", cwd=str(target),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            )
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            if proc.returncode != 0:
                return _text(f"git init failed:\n{out.decode()}")
            name = args.get("name") or target.name
            ptype = (args.get("project_type") or "").strip() or "application"
            if ptype not in ("application", "meta"):
                return _text(f"Error: project_type must be 'application' or 'meta', got {ptype!r}.")
            project, created = await service.create(str(target), name)
            if created:
                file = project_store.read_project_file(target)
                if file:
                    file["project_type"] = ptype
                    project_store.write_project_file(target, file)
                bus.publish("onboarding", "project_registered", {"project": project.model_dump()})
            return _text(
                f"Scaffolded '{name}' at {target} (type={ptype}). "
                f"Git initialized, project registered in Orchid."
            )
        except (OSError, asyncio.TimeoutError) as exc:
            return _text(f"Error: {exc}")

    @tool(
        "add_child_project",
        "Add an existing project as a child of a meta-project. Both must already be registered.",
        {"parent_path": str, "child_project_id": str},
    )
    async def add_child_project(args: dict[str, Any]) -> dict[str, Any]:
        try:
            parent_root = canonicalize(args["parent_path"])
            child_id = args["child_project_id"].strip()
            file = project_store.read_project_file(parent_root)
            if file is None:
                return _text("Error: parent project not registered.")
            if file.get("project_type") != "meta":
                return _text("Error: parent is not a meta-project.")
            child_entry = service._registry.find(child_id)
            if child_entry is None:
                return _text(f"Error: no project with id {child_id}.")
            children = file.get("children") or []
            if child_id in children:
                return _text(f"{child_id} is already a child of this meta-project.")
            children.append(child_id)
            file["children"] = children
            project_store.write_project_file(parent_root, file)
            entry = service._registry.find_by_root(parent_root)
            if entry:
                project = await service._to_project(entry)
                bus.publish("sidebar", "project_updated", {"project": project.model_dump()})
            return _text(f"Added {child_id} as a child. Children: {children}.")
        except OSError as exc:
            return _text(f"Error: {exc}")

    @tool(
        "remove_child_project",
        "Remove a child project from a meta-project (does not delete the child).",
        {"parent_path": str, "child_project_id": str},
    )
    async def remove_child_project(args: dict[str, Any]) -> dict[str, Any]:
        try:
            parent_root = canonicalize(args["parent_path"])
            child_id = args["child_project_id"].strip()
            file = project_store.read_project_file(parent_root)
            if file is None:
                return _text("Error: parent project not registered.")
            children = file.get("children") or []
            if child_id not in children:
                return _text(f"{child_id} is not a child of this meta-project.")
            children.remove(child_id)
            file["children"] = children
            project_store.write_project_file(parent_root, file)
            entry = service._registry.find_by_root(parent_root)
            if entry:
                project = await service._to_project(entry)
                bus.publish("sidebar", "project_updated", {"project": project.model_dump()})
            return _text(f"Removed {child_id}. Children: {children}.")
        except OSError as exc:
            return _text(f"Error: {exc}")

    return [list_directory, inspect_directory, register_project, write_agents_md,
            assign_roles, git_init, ask_choice, set_project_intent,
            scaffold_project, add_child_project, remove_child_project]


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
                "mcp__orchid__write_agents_md",
                "mcp__orchid__assign_roles",
                "mcp__orchid__git_init",
                "mcp__orchid__ask_choice",
                "mcp__orchid__set_project_intent",
                "mcp__orchid__scaffold_project",
                "mcp__orchid__add_child_project",
                "mcp__orchid__remove_child_project",
            ],
            disallowed_tools=["Bash", "Write", "Edit", "NotebookEdit", "WebFetch", "WebSearch", "Task", "AskUserQuestion"],
            permission_mode="bypassPermissions",
        )

    return SessionDriver(runner, spec_factory, bus, topic="onboarding", hold_open=True)
