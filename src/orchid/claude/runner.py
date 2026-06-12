"""The only module family (orchid.claude.*) allowed to import claude_agent_sdk."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Protocol

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient


@dataclass
class RunnerSpec:
    cwd: Path | None = None
    resume: str | None = None
    system_prompt: str | None = None
    allowed_tools: list[str] | None = None
    disallowed_tools: list[str] | None = None
    mcp_servers: dict[str, Any] | None = None
    permission_mode: str | None = None
    setting_sources: list[str] | None = None
    model: str | None = None
    max_turns: int | None = None
    extra_options: dict[str, Any] = field(default_factory=dict)


class RunnerClient(Protocol):
    async def query(self, prompt: str, session_id: str = "default") -> None: ...
    def receive_response(self) -> AsyncIterator[Any]: ...
    async def interrupt(self) -> None: ...


class Runner(Protocol):
    async def open(self, spec: RunnerSpec) -> RunnerClient: ...
    async def close(self, client: RunnerClient) -> None: ...


def _build_options(spec: RunnerSpec) -> ClaudeAgentOptions:
    kwargs: dict[str, Any] = dict(spec.extra_options)
    if spec.cwd is not None:
        kwargs["cwd"] = str(spec.cwd)
    if spec.resume is not None:
        kwargs["resume"] = spec.resume
    if spec.system_prompt is not None:
        kwargs["system_prompt"] = spec.system_prompt
    if spec.allowed_tools is not None:
        kwargs["allowed_tools"] = spec.allowed_tools
    if spec.disallowed_tools is not None:
        kwargs["disallowed_tools"] = spec.disallowed_tools
    if spec.mcp_servers is not None:
        kwargs["mcp_servers"] = spec.mcp_servers
    if spec.permission_mode is not None:
        kwargs["permission_mode"] = spec.permission_mode
    if spec.setting_sources is not None:
        kwargs["setting_sources"] = spec.setting_sources
    if spec.model is not None:
        kwargs["model"] = spec.model
    if spec.max_turns is not None:
        kwargs["max_turns"] = spec.max_turns
    return ClaudeAgentOptions(**kwargs)


class SdkRunner:
    async def open(self, spec: RunnerSpec) -> RunnerClient:
        client = ClaudeSDKClient(options=_build_options(spec))
        await client.connect()
        return client

    async def close(self, client: RunnerClient) -> None:
        await client.disconnect()  # type: ignore[attr-defined]
