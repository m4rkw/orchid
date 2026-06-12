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
        if value > 1e11:  # epoch milliseconds (SDK uses ms; seconds would be year 5138+)
            value = value / 1000
        return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
    return str(value)


def age_seconds(last_modified: Any) -> float | None:
    """Age of an SDKSessionInfo.last_modified value (datetime | epoch s/ms | iso str)."""
    iso = _iso(last_modified)
    if iso is None:
        return None
    try:
        ts = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - ts).total_seconds()


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
        """Transcript-dir keys for a root: canonical plus the macOS symlink alias
        spelling (/private/var/x ↔ /var/x), so externally-started sessions are
        found regardless of how the cwd was recorded."""

        def _keys() -> list[str]:
            spellings = {str(root)}
            s = str(root)
            for real, alias in (("/private/var/", "/var/"), ("/private/tmp/", "/tmp/"), ("/private/etc/", "/etc/")):
                if s.startswith(real):
                    spellings.add(alias + s[len(real):])
                elif s.startswith(alias):
                    spellings.add(real + s[len(alias):])
            keys = []
            for sp in spellings:
                try:
                    key = sdk.project_key_for_directory(sp)
                    if key not in keys:
                        keys.append(key)
                except Exception:
                    continue
            return keys

        return await asyncio.to_thread(_keys)

    async def session_info(self, session_id: str, root: Path) -> Any | None:
        def _info() -> Any | None:
            try:
                return sdk.get_session_info(session_id, directory=str(root))
            except Exception:
                return None

        return await asyncio.to_thread(_info)

    async def session_messages(self, session_id: str, root: Path) -> list[Any]:
        def _messages() -> list[Any]:
            try:
                return sdk.get_session_messages(session_id, directory=str(root))
            except Exception:
                log.debug("get_session_messages failed for %s", session_id, exc_info=True)
                return []

        return await asyncio.to_thread(_messages)

    async def subagents(self, session_id: str, root: Path) -> list[str]:
        def _agents() -> list[str]:
            try:
                return sdk.list_subagents(session_id, directory=str(root))
            except Exception:
                return []

        return await asyncio.to_thread(_agents)

    async def subagent_messages(self, session_id: str, agent_id: str, root: Path) -> list[Any]:
        def _messages() -> list[Any]:
            try:
                return sdk.get_subagent_messages(session_id, agent_id, directory=str(root))
            except Exception:
                return []

        return await asyncio.to_thread(_messages)

    async def rename(self, session_id: str, title: str, root: Path) -> None:
        await asyncio.to_thread(sdk.rename_session, session_id, title, directory=str(root))

    async def delete(self, session_id: str, root: Path) -> None:
        await asyncio.to_thread(sdk.delete_session, session_id, directory=str(root))

    async def fork(self, session_id: str, root: Path, title: str | None = None) -> str:
        def _fork() -> str:
            return sdk.fork_session(session_id, directory=str(root), title=title).session_id

        return await asyncio.to_thread(_fork)
