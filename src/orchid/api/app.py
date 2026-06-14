import asyncio
import importlib.metadata
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__
from ..bus import EventBus
from ..claude.catalog import Catalog
from ..claude.driver_manager import DriverManager
from ..claude.onboarding import build_onboarding_driver
from ..claude.runner import Runner, SdkRunner
from ..claude.transcript import TranscriptCache
from ..config import Settings
from ..services import ApiError, ProjectService, SessionService
from ..store.registry import Registry
from ..watch.watcher import WatcherManager
from . import collaborations, elevation, onboarding_api, permissions, plans, projects, reviews, sessions, ws

_FALLBACK_HTML = """<!doctype html><html><body style="font-family: ui-monospace, monospace;
background:#0b0b0f; color:#d4d4d8; display:grid; place-items:center; height:100vh; margin:0">
<div><h1 style="color:#c084fc">⚘ Orchid</h1>
<p>Frontend not built yet. Run:</p><pre>cd web && npm install && npm run build</pre>
<p>then reload. (API is live at <a href="/api/health" style="color:#c084fc">/api/health</a>.)</p>
</div></body></html>"""


async def _claude_cli_version() -> str | None:
    try:
        proc = await asyncio.create_subprocess_exec(
            "claude", "--version", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
        return out.decode().strip() or None
    except (OSError, asyncio.TimeoutError):
        return None


def create_app(settings: Settings | None = None, runner: Runner | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.orchid_home.mkdir(parents=True, exist_ok=True)
        bus = EventBus()
        catalog = Catalog()
        registry = Registry(settings.registry_path)
        cache = TranscriptCache()
        session_service = SessionService(registry, catalog, cache, bus, settings)
        watcher = WatcherManager(catalog, session_service, settings)
        service = ProjectService(registry, catalog, bus, settings, observers=[watcher])
        active_runner = runner or SdkRunner()
        from ..orchidd.client import OrchiddClient
        orchidd_client = OrchiddClient()
        onboarding = build_onboarding_driver(active_runner, bus, service, settings)
        driver_manager = DriverManager(active_runner, bus, cache, session_service, watcher, settings,
                                       orchidd_client=orchidd_client)
        from ..claude.collaboration import CollaborationManager
        collab_manager = CollaborationManager(driver_manager, registry, bus, settings,
                                                project_service=service)
        session_service.is_running = driver_manager.is_running
        session_service.live_agents = driver_manager.live_agents
        service.is_running = driver_manager.is_running
        app.state.collab_manager = collab_manager
        app.state.driver_manager = driver_manager
        app.state.settings = settings
        app.state.bus = bus
        app.state.catalog = catalog
        app.state.registry = registry
        app.state.cache = cache
        app.state.sessions = session_service
        app.state.watcher = watcher
        app.state.service = service
        app.state.onboarding = onboarding
        app.state.orchidd_client = orchidd_client
        app.state.claude_cli_version = await _claude_cli_version()
        await watcher.start(registry.list())
        await driver_manager.auto_resume()
        yield
        await collab_manager.aclose()
        await driver_manager.aclose()
        await watcher.aclose()
        await onboarding.aclose()
        await orchidd_client.aclose()

    app = FastAPI(title="Orchid", version=__version__, lifespan=lifespan)

    @app.exception_handler(ApiError)
    async def api_error_handler(_request: Request, exc: ApiError):
        return JSONResponse(status_code=exc.status, content={"error": {"code": exc.code, "message": exc.message}})

    @app.get("/api/health")
    async def health(request: Request):
        try:
            sdk_version = importlib.metadata.version("claude-agent-sdk")
        except importlib.metadata.PackageNotFoundError:
            sdk_version = None
        return {
            "version": __version__,
            "claude_cli_version": request.app.state.claude_cli_version,
            "sdk_version": sdk_version,
            "config_dir": str(settings.claude_config_dir),
            "orchid_home": str(settings.orchid_home),
        }

    app.include_router(collaborations.router, prefix="/api")
    app.include_router(projects.router, prefix="/api")
    app.include_router(sessions.router, prefix="/api")
    app.include_router(plans.router, prefix="/api")
    app.include_router(reviews.router, prefix="/api")
    app.include_router(onboarding_api.router, prefix="/api")
    app.include_router(permissions.router, prefix="/api")
    app.include_router(elevation.router, prefix="/api")
    app.include_router(ws.router)

    if settings.web_dist.is_dir():
        app.mount("/", StaticFiles(directory=settings.web_dist, html=True), name="web")
    else:

        @app.get("/", response_class=HTMLResponse)
        async def fallback():
            return _FALLBACK_HTML

    return app


def create_app_from_env() -> FastAPI:
    return create_app()
