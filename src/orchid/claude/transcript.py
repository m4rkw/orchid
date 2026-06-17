import json
import uuid as uuidlib
from datetime import datetime, timezone
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


# Streamed messages often arrive with no SDK uuid yet (e.g. the text chunk before
# tool calls). We tag the placeholder id with this prefix so the cache can tell a
# transient live-only copy (which will be superseded by its persisted, real-uuid
# record) from a genuinely in-flight message and not strand it at the end.
_LIVE_PREFIX = "live-"


def _new_uuid() -> str:
    return uuidlib.uuid4().hex


def _live_uuid() -> str:
    return _LIVE_PREFIX + uuidlib.uuid4().hex


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_stream_message(msg: Any, cap: int = PREVIEW_CAP) -> NormalizedMessage | None:
    """Map an SDK stream message to the wire model; None = nothing to render."""
    if isinstance(msg, SystemMessage):
        return None

    if isinstance(msg, AssistantMessage):
        blocks: list[Block] = []
        for b in msg.content:
            if isinstance(b, TextBlock) and b.text:
                text, truncated = _preview(b.text, cap)
                blocks.append(Block(type="text", text=text, truncated=truncated))
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
            uuid=msg.uuid or _live_uuid(),
            role="assistant",
            agent_id=None,
            blocks=blocks,
            timestamp=_now_iso(),
        )

    if isinstance(msg, UserMessage):
        blocks: list[Block] = []
        if isinstance(msg.content, str):
            if msg.content:
                text, truncated = _preview(msg.content, cap)
                blocks.append(Block(type="text", text=text, truncated=truncated))
        else:
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
        return NormalizedMessage(uuid=msg.uuid or _live_uuid(), role="user", agent_id=None,
                                 blocks=blocks, timestamp=_now_iso())

    if isinstance(msg, ResultMessage):
        parts = ["turn done"]
        if msg.total_cost_usd is not None:
            parts.append(f"${msg.total_cost_usd:.4f}")
        parts.append(f"{msg.duration_ms / 1000:.1f}s")
        return NormalizedMessage(
            uuid=msg.uuid or _live_uuid(),
            role="result",
            agent_id=None,
            blocks=[Block(type="text", text=" · ".join(parts))],
            timestamp=_now_iso(),
        )

    return None  # StreamEvent / RateLimitEvent etc. arrive in M3


def _blocks_from_raw_content(content: Any, cap: int) -> list[Block]:
    if isinstance(content, str):
        text, truncated = _preview(content, cap)
        return [Block(type="text", text=text, truncated=truncated)] if content else []
    blocks: list[Block] = []
    if not isinstance(content, list):
        return blocks
    for b in content:
        if not isinstance(b, dict):
            continue
        btype = b.get("type")
        if btype == "text" and b.get("text"):
            text, truncated = _preview(b["text"], cap)
            blocks.append(Block(type="text", text=text, truncated=truncated))
        elif btype == "thinking" and b.get("thinking"):
            text, truncated = _preview(b["thinking"], cap)
            blocks.append(Block(type="thinking", text=text, truncated=truncated))
        elif btype == "tool_use":
            preview, truncated = _preview(b.get("input", {}), cap)
            blocks.append(
                Block(type="tool_use", id=b.get("id"), name=b.get("name", "?"),
                      input_preview=preview, truncated=truncated)
            )
        elif btype == "tool_result":
            preview, truncated = _preview(_result_content_text(b.get("content")), cap)
            blocks.append(
                Block(type="tool_result", tool_use_id=b.get("tool_use_id"),
                      content_preview=preview, is_error=bool(b.get("is_error")), truncated=truncated)
            )
    return blocks


def normalize_record(rec: Any, cap: int = PREVIEW_CAP, agent_id: str | None = None) -> NormalizedMessage | None:
    """Map an at-rest SessionMessage (from get_session_messages) to the wire model.

    Unlike the live stream, at-rest user prompts must render (full transcript view).
    """
    if rec.type not in ("user", "assistant"):
        return None
    message = rec.message
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    if isinstance(content, list) and len(content) == 1:
        only = content[0]
        if isinstance(only, dict) and only.get("type") == "text":
            text = only.get("text", "")
            if text.startswith("[Request interrupted"):
                return None
    blocks = _blocks_from_raw_content(content, cap)
    if not blocks:
        return None
    return NormalizedMessage(
        uuid=rec.uuid or _new_uuid(),
        role="assistant" if rec.type == "assistant" else "user",
        agent_id=agent_id,
        blocks=blocks,
    )


class TranscriptCache:
    """Per-session normalized message lists with uuid-based diffing.

    The SDK has no incremental read, so refresh is full re-read + diff; the bus
    seq (owned by EventBus per session topic) is the client's replay watermark.
    """

    def __init__(self, max_messages: int = 2000):
        self._max = max_messages
        self._messages: dict[str, list[NormalizedMessage]] = {}
        self._seen: dict[str, set[str]] = {}

    def get(self, session_id: str) -> list[NormalizedMessage] | None:
        return self._messages.get(session_id)

    def message_count(self, session_id: str) -> int:
        return len(self._messages.get(session_id, []))

    def ingest(self, session_id: str, normalized: list[NormalizedMessage]) -> list[NormalizedMessage]:
        """Merge a full re-read; returns only the messages not seen before.

        Disk order is authoritative — if live-streamed messages arrived before
        the disk read, the list is rebuilt in JSONL order so responses never
        appear before the prompts that triggered them.
        """
        seen = self._seen.setdefault(session_id, set())
        messages = self._messages.setdefault(session_id, [])
        fresh = [m for m in normalized if m.uuid not in seen]
        for m in normalized:
            seen.add(m.uuid)
        disk_uuids = {m.uuid for m in normalized}
        # Keep genuinely in-flight messages (real uuids not yet persisted), but
        # drop transient streamed copies (synthetic "live-" uuids): their persisted
        # counterpart is already in `normalized`, so re-appending would duplicate
        # the message and strand the stale copy at the end of the transcript.
        live_only = [
            m for m in messages
            if m.uuid not in disk_uuids and not m.uuid.startswith(_LIVE_PREFIX)
        ]
        # Carry live-observed receipt timestamps onto the re-read disk copies (the
        # SDK doesn't surface them), so navigating away/back doesn't lose them.
        prior_ts = {m.uuid: m.timestamp for m in messages if m.timestamp}
        for m in normalized:
            if m.timestamp is None and m.uuid in prior_ts:
                m.timestamp = prior_ts[m.uuid]
        messages.clear()
        messages.extend(normalized)
        messages.extend(live_only)
        if len(messages) > self._max:
            del messages[: len(messages) - self._max]
        return fresh

    def append_live(self, session_id: str, message: NormalizedMessage) -> bool:
        """Add a message arriving from a live driver stream; False if duplicate."""
        seen = self._seen.setdefault(session_id, set())
        if message.uuid in seen:
            return False
        seen.add(message.uuid)
        self._messages.setdefault(session_id, []).append(message)
        return True

    def drop(self, session_id: str) -> None:
        self._messages.pop(session_id, None)
        self._seen.pop(session_id, None)
