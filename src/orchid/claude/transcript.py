import json
import uuid as uuidlib
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from ..models import Block, NormalizedMessage

PREVIEW_CAP = 16384


def _preview(value: Any, cap: int = PREVIEW_CAP) -> tuple[str, bool]:
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, default=str)
        except (TypeError, ValueError):
            text = str(value)
    return (text[:cap], len(text) > cap)


def _result_content_text(content: Any) -> Any:
    """Tool result content is str | list[{type: text,...}] | None."""
    if isinstance(content, list):
        texts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
        if texts:
            return "\n".join(texts)
    return content


def _new_uuid() -> str:
    return uuidlib.uuid4().hex


def normalize_stream_message(msg: Any, cap: int = PREVIEW_CAP) -> NormalizedMessage | None:
    """Map an SDK stream message to the wire model; None = nothing to render."""
    if isinstance(msg, SystemMessage):
        return None

    if isinstance(msg, AssistantMessage):
        blocks: list[Block] = []
        for b in msg.content:
            if isinstance(b, TextBlock) and b.text:
                blocks.append(Block(type="text", text=b.text))
            elif isinstance(b, ThinkingBlock) and b.thinking:
                text, truncated = _preview(b.thinking, cap)
                blocks.append(Block(type="thinking", text=text, truncated=truncated))
            elif isinstance(b, ToolUseBlock):
                preview, truncated = _preview(b.input, cap)
                blocks.append(
                    Block(type="tool_use", id=b.id, name=b.name, input_preview=preview, truncated=truncated)
                )
        if not blocks:
            return None
        return NormalizedMessage(
            uuid=msg.uuid or _new_uuid(),
            role="assistant",
            agent_id=None,
            blocks=blocks,
        )

    if isinstance(msg, UserMessage):
        if isinstance(msg.content, str):
            return None  # prompt echo; the UI renders user prompts locally
        blocks = []
        for b in msg.content:
            if isinstance(b, ToolResultBlock):
                preview, truncated = _preview(_result_content_text(b.content), cap)
                blocks.append(
                    Block(
                        type="tool_result",
                        tool_use_id=b.tool_use_id,
                        content_preview=preview,
                        is_error=bool(b.is_error),
                        truncated=truncated,
                    )
                )
        if not blocks:
            return None
        return NormalizedMessage(uuid=msg.uuid or _new_uuid(), role="user", agent_id=None, blocks=blocks)

    if isinstance(msg, ResultMessage):
        parts = ["turn done"]
        if msg.total_cost_usd is not None:
            parts.append(f"${msg.total_cost_usd:.4f}")
        parts.append(f"{msg.duration_ms / 1000:.1f}s")
        return NormalizedMessage(
            uuid=msg.uuid or _new_uuid(),
            role="result",
            agent_id=None,
            blocks=[Block(type="text", text=" · ".join(parts))],
        )

    return None  # StreamEvent / RateLimitEvent etc. arrive in M3
