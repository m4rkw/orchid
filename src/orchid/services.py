from pathlib import Path

from .bus import EventBus
from .claude.catalog import Catalog
from .config import Settings
from .models import Project, SessionSummary
from .store import project_store
from .store.paths import canonicalize
from .store.registry import Registry, new_project_id


class ApiError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


class ProjectService:
    """Project CRUD shared by the REST API and the onboarding chat tools."""

    def __init__(self, registry: Registry, catalog: Catalog, bus: EventBus, settings: Settings):
        self._registry = registry
        self._catalog = catalog
        self._bus = bus
        self._settings = settings

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

    async def sessions(self, project_id: str) -> list[SessionSummary]:
        root = Path(self.get_entry(project_id)["root"])
        flags = project_store.get_session_flags(root)
        summaries = await self._catalog.list_sessions(root, flags)
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
