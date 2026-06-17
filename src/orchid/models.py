from typing import Literal

from pydantic import BaseModel

SessionStatus = Literal["idle", "running", "external"]


class ProjectSettingsModel(BaseModel):
    model: str | None = None
    permission_mode: str = "acceptEdits"
    test_command: str | None = None  # used by on-demand review verification


class Project(BaseModel):
    id: str
    name: str
    root: str
    session_count: int = 0
    missing: bool = False
    intent: Literal["adhoc", "goal"] | None = None
    goal: str | None = None
    review_mode: Literal["manual", "autonomous"] | None = None
    project_type: Literal["application", "meta"] | None = None
    children: list[str] = []


class SessionSummary(BaseModel):
    id: str
    title: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    status: SessionStatus = "idle"
    message_count: int = 0
    pinned: bool = False
    archived: bool = False
    created_by: Literal["orchid", "external"] = "external"
    role: str | None = None


class SessionDetail(SessionSummary):
    project_id: str
    handoff_command: str
    cost_usd: float | None = None
    turns: int = 0


class AgentInfo(BaseModel):
    agent_id: str
    message_count: int = 0
    status: Literal["running", "done"] = "done"


# -- agent roles & plans ----------------------------------------------------

# orchestrator = the session you drive; subagent = materialized via the SDK
# `agents=` option; infra = a role already covered by Orchid/the model, shipped
# as an off-by-default template so the full taxonomy stays visible and editable.
RoleKind = Literal["orchestrator", "subagent", "infra"]


class RoleTemplate(BaseModel):
    slug: str
    name: str
    summary: str  # one-liner shown in the UI
    kind: RoleKind
    enabled: bool = True
    prompt: str = ""  # appended to the orchestrator prompt, or the subagent's prompt
    model: str | None = None
    tools: list[str] | None = None  # allowed tools (subagents only)
    disallowed_tools: list[str] | None = None
    note: str | None = None  # e.g. "covered by Orchid's permission broker"


class PlanStep(BaseModel):
    id: str
    title: str
    status: Literal["pending", "in_progress", "done", "blocked"] = "pending"
    roles: list[str] = []
    notes: str | None = None


class Plan(BaseModel):
    id: str
    title: str
    goal: str = ""
    status: Literal["active", "done", "abandoned"] = "active"
    steps: list[PlanStep] = []
    created_at: str | None = None
    updated_at: str | None = None


class Block(BaseModel):
    type: Literal["text", "thinking", "tool_use", "tool_result"]
    text: str | None = None
    id: str | None = None
    name: str | None = None
    input_preview: str | None = None
    tool_use_id: str | None = None
    content_preview: str | None = None
    is_error: bool | None = None
    truncated: bool | None = None


class NormalizedMessage(BaseModel):
    uuid: str
    role: Literal["user", "assistant", "system", "result"]
    agent_id: str | None = None
    blocks: list[Block]
    # ISO-8601 receipt time, stamped when Orchid first observes the message live.
    # None for at-rest messages read back from disk (the SDK doesn't surface the
    # transcript's per-message timestamp); preserved across in-process re-reads.
    timestamp: str | None = None
