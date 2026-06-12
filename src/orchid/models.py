from typing import Literal

from pydantic import BaseModel

SessionStatus = Literal["idle", "running", "external"]


class ProjectSettingsModel(BaseModel):
    model: str | None = None
    permission_mode: str = "acceptEdits"


class Project(BaseModel):
    id: str
    name: str
    root: str
    session_count: int = 0
    missing: bool = False


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
