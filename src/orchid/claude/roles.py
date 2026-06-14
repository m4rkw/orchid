"""Built-in agent-role templates and orchestrator assembly.

Lean by design. The user's 8-role taxonomy is a useful conceptual lens, but in a
coding agent most of it is already provided by the model itself or by Orchid's
infrastructure, so only a few roles are *materialized*:

- orchestrator — the session you drive (not a subagent). Plans, persists the
  plan to disk, and delegates to the subagents below.
- worker / reviewer / verifier — Claude Code subagents (the SDK `agents=` option)
  the orchestrator dispatches to via the Task tool.

The remaining four (router, retriever, memory, tool/action) ship as off-by-default
templates with a note explaining what already covers them, so the full taxonomy
stays visible and editable without running redundant agents.

This is the only place outside the rest of claude/ that builds AgentDefinition;
keeping the SDK import here honours the "SDK only under claude/" hard rule.
"""

from pathlib import Path

from claude_agent_sdk import AgentDefinition

from ..models import RoleTemplate
from ..store import agents_store, project_store

# Tools a non-editing role may use (reviewer/verifier). Edits are reserved for
# the worker; everything risky still passes the permission broker.
_READONLY_TOOLS = ["Read", "Grep", "Glob", "Bash"]
_NO_EDIT = ["Edit", "Write", "NotebookEdit"]


BUILTIN_ROLES: list[RoleTemplate] = [
    RoleTemplate(
        slug="orchestrator",
        name="Orchestrator / Planner",
        summary="Decomposes the goal, keeps the plan on disk, and delegates to the other agents.",
        kind="orchestrator",
        enabled=True,
        prompt=(
            "You are the orchestrator for this project. Decompose the user's goal into a short, "
            "ordered plan and keep it on disk with the plan tools so it survives context loss. "
            "Do the lightest thing that works: handle small changes yourself, and delegate "
            "discrete or parallelisable tasks to your subagents via the Task tool. Always confirm "
            "work with the verifier before marking a step done. Prefer simple, existing patterns."
        ),
    ),
    RoleTemplate(
        slug="worker",
        name="Worker / Executor",
        summary="Implements one scoped task: focused code edits that follow the project's conventions.",
        kind="subagent",
        enabled=True,
        prompt=(
            "You implement one well-scoped task handed to you by the orchestrator. Read the "
            "relevant code and AGENTS.md first, make focused edits that match the surrounding "
            "style, and report exactly what you changed (files + a one-line rationale). Do not "
            "expand scope; if the task is ambiguous or larger than described, say so and stop."
        ),
    ),
    RoleTemplate(
        slug="reviewer",
        name="Reviewer / Critic",
        summary="Independently reviews changes for correctness, security, and simplicity. Does not edit.",
        kind="subagent",
        enabled=True,
        prompt=(
            "You are an independent reviewer. Examine the changes for correctness bugs, security "
            "issues, and needless complexity. Confirm the work was actually verified: read the "
            "attached verification output rather than trusting the summary, and if the branch "
            "modifies tests, check they were not weakened or made tautological to make a failing "
            "change pass. You do NOT modify code — report findings as file:line with a severity "
            "and a concrete suggested fix. Be specific; skip praise."
        ),
        tools=_READONLY_TOOLS,
        disallowed_tools=_NO_EDIT,
    ),
    RoleTemplate(
        slug="verifier",
        name="Verifier / Validator",
        summary="Runs the project's tests/typecheck/lint and reports pass/fail. Deterministic, no edits.",
        kind="subagent",
        enabled=True,
        prompt=(
            "You verify work by RUNNING the project's checks — tests, typecheck, lint, build — "
            "as documented in AGENTS.md, and reporting pass/fail with the exact failing output. "
            "You do not fix anything; you are the deterministic signal the orchestrator trusts."
        ),
        tools=_READONLY_TOOLS,
        disallowed_tools=_NO_EDIT,
    ),
    RoleTemplate(
        slug="router",
        name="Router / Dispatcher",
        summary="Classifies and routes work to the right agent.",
        kind="infra",
        enabled=False,
        note="Covered by the orchestrator: Claude already routes tasks to the right subagent — a separate dispatcher adds latency without value.",
    ),
    RoleTemplate(
        slug="retriever",
        name="Retriever",
        summary="Fetches relevant context to ground the work.",
        kind="infra",
        enabled=False,
        note="Covered by Grep/Glob/Read (and MCP tools): the model retrieves code context directly — no separate retriever or vector store for a codebase.",
    ),
    RoleTemplate(
        slug="memory",
        name="Memory manager",
        summary="Maintains short- and long-term state across the work.",
        kind="infra",
        enabled=False,
        note="Covered by files: AGENTS.md is long-term memory and .orchid/plans is the durable plan, on top of the harness's own context management.",
    ),
    RoleTemplate(
        slug="tool_action",
        name="Tool / Action layer",
        summary="Guards side-effecting actions behind approvals and idempotency.",
        kind="infra",
        enabled=False,
        note="Covered by Orchid's permission broker: risky tools already surface as web approvals under the project's permission_mode.",
    ),
]

_BUILTIN_BY_SLUG = {r.slug: r for r in BUILTIN_ROLES}
_OVERRIDABLE = {"enabled", "name", "summary", "prompt", "model", "tools", "disallowed_tools", "note"}

BRANCH_WORKFLOW_INSTRUCTIONS = (
    "All work must be done in feature branches — never commit directly to main. "
    "Use create_branch to start a new branch for each plan step or unit of work. "
    "Commit frequently with descriptive messages using git_commit. "
    "Check your work with git_status and git_diff before committing. "
    "When a step is complete and verified, call request_review to submit the branch — pass the "
    "verifier's exact output (test/typecheck/lint command + result) in the `verification` field; "
    "a review submitted without evidence is treated as unverified. "
    "Wait for review feedback before proceeding to the next step."
)

PLANNER_INSTRUCTIONS = (
    "Keep your plan on disk with the plan tools (create_plan, add_step, update_step, "
    "set_plan_status) so it outlives this conversation. Create a plan when you start real work, "
    "give each step a clear title and the role(s) it needs, and update step status as you go. "
    "When asked to implement a specific step, first re-read the plan (list_plans / get_plan), "
    "delegate to the relevant subagent(s), have the verifier confirm, then update the step."
)


def resolve_roles(root: Path) -> list[RoleTemplate]:
    """Built-in templates merged with this project's saved overrides (agents.json)."""
    overrides = agents_store.read_agent_overrides(root)
    out: list[RoleTemplate] = []
    for tpl in BUILTIN_ROLES:
        clean = {k: v for k, v in overrides.get(tpl.slug, {}).items() if k in _OVERRIDABLE}
        out.append(RoleTemplate(**{**tpl.model_dump(), **clean}) if clean else tpl)
    return out


def normalize_overrides(roles: list[dict] | dict[str, dict]) -> dict[str, dict]:
    """Reduce an incoming roles payload to sparse overrides (only fields that differ
    from the built-in default), keyed by slug — so agents.json stays minimal and
    future template edits flow through. Unknown slugs are dropped."""
    items = roles.items() if isinstance(roles, dict) else ((r.get("slug"), r) for r in roles)
    out: dict[str, dict] = {}
    for slug, payload in items:
        base = _BUILTIN_BY_SLUG.get(slug)
        if base is None or not isinstance(payload, dict):
            continue
        base_dump = base.model_dump()
        delta = {
            k: payload[k]
            for k in _OVERRIDABLE
            if k in payload and payload[k] != base_dump.get(k)
        }
        if delta:
            out[slug] = delta
    return out


def _read_agents_md(root: Path) -> str:
    agents_md = root / "AGENTS.md"
    if agents_md.is_file():
        try:
            return agents_md.read_text(errors="replace").strip()
        except OSError:
            pass
    return ""


def _project_goal_section(root: Path) -> str:
    """The project's persisted goal/intent as a system-prompt block, so a session
    started with a terse prompt (e.g. "plan milestones") is still anchored to what
    the project is working towards. Empty when the project has no stated goal."""
    proj = project_store.read_project_file(root) or {}
    goal = (proj.get("goal") or "").strip()
    if not goal:
        return ""
    intent = proj.get("intent") or "goal"
    review = proj.get("review_mode")
    lead = f"This project is {intent}-oriented"
    if review:
        lead += f"; reviews are {review}"
    return f"# Project goal\n\n{lead}.\n\nGoal: {goal}"


def assemble_orchestrator(
    root: Path, child_roots: list[Path] | None = None,
) -> tuple[dict[str, AgentDefinition], str]:
    """Produce the SDK `agents=` map (enabled subagents) and the system-prompt
    append (orchestrator role + roster + planner instructions + AGENTS.md) for an
    orchestrator session in `root`.

    For meta-projects, pass `child_roots` — each child's AGENTS.md is injected
    under a heading so the orchestrator has full cross-project context.
    """
    roles = resolve_roles(root)
    subagents = [r for r in roles if r.kind == "subagent" and r.enabled]
    agents = {
        r.slug: AgentDefinition(
            description=r.summary,
            prompt=r.prompt,
            tools=r.tools,
            disallowedTools=r.disallowed_tools,
            model=r.model,
        )
        for r in subagents
    }

    parts: list[str] = []
    orch = next((r for r in roles if r.slug == "orchestrator"), None)
    if orch and orch.enabled and orch.prompt.strip():
        parts.append(orch.prompt.strip())
    if subagents:
        roster = "\n".join(f"- {r.slug}: {r.summary}" for r in subagents)
        parts.append(
            "Delegate discrete tasks to these subagents with the Task tool (use the name):\n"
            + roster
        )
    goal_section = _project_goal_section(root)
    if goal_section:
        parts.append(goal_section)
    parts.append(PLANNER_INSTRUCTIONS)
    parts.append(BRANCH_WORKFLOW_INSTRUCTIONS)

    text = _read_agents_md(root)
    if text:
        parts.append("# Project context (AGENTS.md)\n\n" + text)

    for child in child_roots or []:
        child_text = _read_agents_md(child)
        if child_text:
            parts.append(f"# Child project: {child.name} ({child})\n\n{child_text}")

    return agents, "\n\n".join(parts)
