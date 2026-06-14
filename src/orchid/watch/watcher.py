import asyncio
import logging
from pathlib import Path

from watchfiles import awatch

from ..claude.catalog import Catalog
from ..models import Project
from ..services import SessionService
from ..store import project_store
from ..config import Settings

log = logging.getLogger(__name__)


class WatcherManager:
    """One watchfiles task over <claude_config>/projects/, routing transcript
    changes to SessionService.refresh_from_disk by project key.

    This is how Orchid-owned sessions stream into the web UI when their files
    change. Only sessions Orchid created are routed — terminal-started
    transcripts in a watched directory are ignored, so Orchid never surfaces or
    streams a session it doesn't own. Driver-active session ids are additionally
    suppressed (M3) to keep one-writer semantics during a burst.
    """

    def __init__(self, catalog: Catalog, sessions: SessionService, settings: Settings):
        self._catalog = catalog
        self._sessions = sessions
        self._settings = settings
        self._key_map: dict[str, tuple[str, Path]] = {}  # transcript key -> (project_id, root)
        self._suppressed: set[str] = set()
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None

    async def start(self, entries: list[dict]) -> None:
        for entry in entries:
            await self._register(entry["id"], Path(entry["root"]))
        self._task = asyncio.create_task(self._run(), name="watcher")

    async def project_added(self, project: Project) -> None:
        await self._register(project.id, Path(project.root))

    async def project_removed(self, project_id: str) -> None:
        self._key_map = {k: v for k, v in self._key_map.items() if v[0] != project_id}

    def suppress(self, session_id: str) -> None:
        self._suppressed.add(session_id)

    def unsuppress(self, session_id: str) -> None:
        self._suppressed.discard(session_id)

    async def aclose(self) -> None:
        self._stop.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _register(self, project_id: str, root: Path) -> None:
        for key in await self._catalog.project_keys(root):
            self._key_map[key] = (project_id, root)

    @property
    def _base(self) -> Path:
        return self._settings.claude_config_dir / "projects"

    async def _run(self) -> None:
        while not self._stop.is_set():
            if not self._base.is_dir():
                await asyncio.sleep(2)
                continue
            try:
                async for changes in awatch(self._base, debounce=300, step=50, stop_event=self._stop):
                    await self._handle({raw for _change, raw in changes})
            except (RuntimeError, OSError):
                log.warning("watcher loop error; restarting", exc_info=True)
            await asyncio.sleep(1)

    def _target_of(self, raw_path: str) -> tuple[str, str, Path] | None:
        """Map a changed path to (session_id, project_id, root) or None."""
        try:
            rel = Path(raw_path).relative_to(self._base)
        except ValueError:
            return None
        parts = rel.parts
        if len(parts) < 2:
            return None
        mapped = self._key_map.get(parts[0])
        if mapped is None:
            return None
        # <key>/<sid>.jsonl (main transcript) or <key>/<sid>/subagents/agent-*.jsonl
        if len(parts) == 2 and parts[1].endswith(".jsonl"):
            sid = parts[1].removesuffix(".jsonl")
        elif len(parts) >= 4 and parts[2] == "subagents":
            sid = parts[1]
        else:
            return None
        return sid, mapped[0], mapped[1]

    async def _handle(self, raw_paths: set[str]) -> None:
        targets: dict[str, tuple[str, Path]] = {}
        for raw in raw_paths:
            hit = self._target_of(raw)
            if hit:
                targets[hit[0]] = (hit[1], hit[2])
        for sid, (project_id, root) in targets.items():
            if sid in self._suppressed:
                continue
            if not project_store.is_orchid_session(root, sid):
                continue  # terminal-started session — not ours to surface or stream
            try:
                await self._sessions.refresh_from_disk(sid, project_id, root)
            except Exception:
                log.warning("refresh failed for session %s", sid, exc_info=True)
