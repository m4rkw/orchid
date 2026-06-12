from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from .bus import EventBus
from .claude.catalog import Catalog, map_summary
from .claude.transcript import TranscriptCache, normalize_record
from .config import Settings
from .models import AgentInfo, NormalizedMessage, Project, SessionDetail, SessionSummary
from .store import project_store
from .store.paths import canonicalize, handoff_command
from .store.registry import Registry, new_project_id


class ApiError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


class ProjectObserver(Protocol):
    async def project_added(self, project: Project) -> None: ...
    async def project_removed(self, project_id: str) -> None: ...


class ProjectService:
    """Project CRUD shared by the REST API and the onboarding chat tools."""

    def __init__(
        self,
        registry: Registry,
        catalog: Catalog,
        bus: EventBus,
        settings: Settings,
        observers: list[ProjectObserver] | None = None,
    ):
        self._registry = registry
        self._catalog = catalog
        self._bus = bus
        self._settings = settings
        self._observers = observers if observers is not None else []

    async def create(self, path: str, name: str | None = None) -> tuple[Project, bool]:
        root = canonicalize(path)
        if not root.exists():
            raise ApiError("PATH_NOT_FOUND", f"path does not exist: {root}", 400)
        if not root.is_dir():
            raise ApiError("NOT_A_DIRECTORY", f"not a directory: {root}", 400)

        existing = self._registry.find_by_root(root)
        if existing:
            return await self._to_project(existing), False

        project_id = new_project_id()
        file = project_store.init_project(root, project_id, name or root.name)
        # init_project is idempotent: a pre-existing .orchid/ keeps its original id
        entry = self._registry.add(file["id"], root)
        project = await self._to_project(entry)
        self._bus.publish("sidebar", "project_added", {"project": project.model_dump()})
        for observer in self._observers:
            await observer.project_added(project)
        return project, True

    async def list_projects(self) -> list[Project]:
        return [await self._to_project(e) for e in self._registry.list()]

    def get_entry(self, project_id: str) -> dict:
        entry = self._registry.find(project_id)
        if not entry:
            raise ApiError("PROJECT_NOT_FOUND", f"no project {project_id}", 404)
        return entry

    async def remove(self, project_id: str) -> None:
        if not self._registry.remove(project_id):
            raise ApiError("PROJECT_NOT_FOUND", f"no project {project_id}", 404)
        self._bus.publish("sidebar", "project_removed", {"project_id": project_id})
        for observer in self._observers:
            await observer.project_removed(project_id)

    async def sessions(self, project_id: str) -> list[SessionSummary]:
        root = Path(self.get_entry(project_id)["root"])
        flags = project_store.get_session_flags(root)
        summaries = await self._catalog.list_sessions(root, flags)
        for s in summaries:
            s.status = status_from_updated(s.updated_at, self._settings.external_window_s)
        summaries.sort(key=lambda s: s.updated_at or "", reverse=True)
        summaries.sort(key=lambda s: not s.pinned)
        return summaries

    async def _to_project(self, entry: dict) -> Project:
        root = Path(entry["root"])
        file = project_store.read_project_file(root) if root.exists() else None
        missing = file is None
        count = 0 if missing else len(await self._catalog.list_sessions(root, {}))
        return Project(
            id=entry["id"],
            name=(file or {}).get("name", root.name),
            root=str(root),
            session_count=count,
            missing=missing,
        )


def status_from_updated(updated_at: str | None, window_s: float) -> str:
    """external = transcript touched recently by something that isn't an Orchid driver."""
    if not updated_at:
        return "idle"
    try:
        updated = datetime.fromisoformat(updated_at)
    except ValueError:
        return "idle"
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - updated).total_seconds()
    return "external" if 0 <= age < window_s else "idle"


class SessionService:
    """Session reads spanning the registry, SDK catalog, and transcript cache."""

    def __init__(
        self,
        registry: Registry,
        catalog: Catalog,
        cache: TranscriptCache,
        bus: EventBus,
        settings: Settings,
    ):
        self._registry = registry
        self._catalog = catalog
        self._cache = cache
        self._bus = bus
        self._settings = settings
        self._locations: dict[str, str] = {}  # session_id -> project_id

    async def locate(self, session_id: str) -> tuple[dict, Any]:
        """Find which onboarded project a session belongs to -> (registry entry, SDKSessionInfo)."""
        entries = self._registry.list()
        cached_pid = self._locations.get(session_id)
        entries.sort(key=lambda e: e["id"] != cached_pid)
        for entry in entries:
            info = await self._catalog.session_info(session_id, Path(entry["root"]))
            if info is not None:
                self._locations[session_id] = entry["id"]
                return entry, info
        raise ApiError("SESSION_NOT_FOUND", f"no session {session_id} in any onboarded project", 404)

    def _summary(self, session_id: str, info: Any, root: Path) -> SessionSummary:
        flags = project_store.get_session_flags(root).get(session_id, {})
        summary = map_summary(info, flags)
        summary.status = status_from_updated(summary.updated_at, self._settings.external_window_s)
        summary.message_count = self._cache.message_count(session_id)
        return summary

    async def detail(self, session_id: str) -> SessionDetail:
        entry, info = await self.locate(session_id)
        root = Path(entry["root"])
        summary = self._summary(session_id, info, root)
        return SessionDetail(
            **summary.model_dump(),
            project_id=entry["id"],
            handoff_command=handoff_command(root, session_id),
        )

    async def _load_cache(self, session_id: str, root: Path) -> None:
        records = await self._catalog.session_messages(session_id, root)
        normalized = [m for m in (normalize_record(r) for r in records) if m is not None]
        self._cache.ingest(session_id, normalized)

    async def messages(self, session_id: str) -> dict[str, Any]:
        entry, _info = await self.locate(session_id)
        if self._cache.get(session_id) is None:
            await self._load_cache(session_id, Path(entry["root"]))
        return {
            "messages": [m.model_dump() for m in self._cache.get(session_id) or []],
            "seq": self._bus.current_seq(f"session:{session_id}"),
        }

    async def full_message(self, session_id: str, uuid: str) -> NormalizedMessage:
        entry, _info = await self.locate(session_id)
        records = await self._catalog.session_messages(session_id, Path(entry["root"]))
        for rec in records:
            if rec.uuid == uuid:
                full = normalize_record(rec, cap=1_000_000_000)
                if full is not None:
                    return full
        raise ApiError("MESSAGE_NOT_FOUND", f"no message {uuid} in session {session_id}", 404)

    async def agents(self, session_id: str) -> list[AgentInfo]:
        entry, _info = await self.locate(session_id)
        root = Path(entry["root"])
        agent_ids = await self._catalog.subagents(session_id, root)
        out = []
        for agent_id in agent_ids:
            msgs = await self._catalog.subagent_messages(session_id, agent_id, root)
            out.append(AgentInfo(agent_id=agent_id, message_count=len(msgs)))
        return out

    async def agent_messages(self, session_id: str, agent_id: str) -> dict[str, Any]:
        entry, _info = await self.locate(session_id)
        records = await self._catalog.subagent_messages(session_id, agent_id, Path(entry["root"]))
        normalized = [
            m for m in (normalize_record(r, agent_id=agent_id) for r in records) if m is not None
        ]
        return {"messages": [m.model_dump() for m in normalized]}

    async def refresh_from_disk(self, session_id: str, project_id: str, root: Path) -> None:
        """Watcher path: external change -> diff -> push deltas + sidebar upsert."""
        first_load = self._cache.get(session_id) is None
        records = await self._catalog.session_messages(session_id, root)
        normalized = [m for m in (normalize_record(r) for r in records) if m is not None]
        fresh = self._cache.ingest(session_id, normalized)
        if not first_load:
            topic = f"session:{session_id}"
            for m in fresh:
                self._bus.publish(topic, "message", {"message": m.model_dump()})
        info = await self._catalog.session_info(session_id, root)
        if info is not None:
            summary = self._summary(session_id, info, root)
            self._bus.publish(
                "sidebar",
                "session_upserted",
                {"project_id": project_id, "session": summary.model_dump()},
            )
