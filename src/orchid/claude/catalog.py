import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import claude_agent_sdk as sdk

from ..models import SessionSummary

log = logging.getLogger(__name__)


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
    return str(value)


def map_summary(info: Any, flags: dict[str, Any]) -> SessionSummary:
    """Pure mapping from SDKSessionInfo (+ Orchid flags) to the wire model."""
    title = info.custom_title or info.summary
    if not title and info.first_prompt:
        first = " ".join(str(info.first_prompt).split())
        title = first[:80] + ("…" if len(first) > 80 else "")
    return SessionSummary(
        id=info.session_id,
        title=title or None,
        created_at=_iso(info.created_at),
        updated_at=_iso(info.last_modified),
        status="idle",
        message_count=0,
        pinned=bool(flags.get("pinned", False)),
        archived=bool(flags.get("archived", False)),
        created_by="orchid" if flags.get("created_by") == "orchid" else "external",
    )


class Catalog:
    """At-rest session reads via the SDK catalog functions (run in threads: sync file IO)."""

    async def list_sessions(self, root: Path, flags: dict[str, dict[str, Any]]) -> list[SessionSummary]:
        def _list() -> list[Any]:
            try:
                return sdk.list_sessions(directory=str(root))
            except Exception:  # missing project dir, unreadable files, etc.
                log.debug("list_sessions failed for %s", root, exc_info=True)
                return []

        infos = await asyncio.to_thread(_list)
        return [map_summary(i, flags.get(i.session_id, {})) for i in infos]

    async def project_keys(self, root: Path) -> list[str]:
        def _keys() -> list[str]:
            return [sdk.project_key_for_directory(str(root))]

        return await asyncio.to_thread(_keys)
