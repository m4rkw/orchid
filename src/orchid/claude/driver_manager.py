import asyncio
import logging
import time
import uuid as uuidlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

from ..bus import EventBus
from ..config import Settings
from ..services import ApiError, SessionService
from ..store import project_store
from ..watch.watcher import WatcherManager
from .catalog import age_seconds
from .driver import SessionDriver
from .runner import Runner, RunnerSpec
from .transcript import TranscriptCache, _preview

log = logging.getLogger(__name__)

PERMISSION_TIMEOUT_S = 300.0
POST_BURST_GRACE_S = 2.0


class DriverManager:
    """One driver per session id; permission brokering; two-writer guards."""

    def __init__(
        self,
        runner: Runner,
        bus: EventBus,
        cache: TranscriptCache,
        sessions: SessionService,
        watcher: WatcherManager,
        settings: Settings,
    ):
        self._runner = runner
        self._bus = bus
        self._cache = cache
        self._sessions = sessions
        self._watcher = watcher
        self._settings = settings
        self._drivers: dict[str, SessionDriver] = {}
        self._projects_of: dict[str, str] = {}  # sid -> project_id
        self._perms: dict[str, tuple[asyncio.Future, str | None]] = {}
        self._last_burst_end: dict[str, float] = {}
        self._resync_tasks: set[asyncio.Task] = set()

    # -- status -------------------------------------------------------------

    def is_running(self, session_id: str) -> bool:
        d = self._drivers.get(session_id)
        return bool(d and (d.state == "running" or d.queue_len > 0))

    def queue_len(self, session_id: str) -> int:
        d = self._drivers.get(session_id)
        return d.queue_len if d else 0

    # -- driver construction --------------------------------------------------

    def _build_driver(self, root: Path, project_id: str, *, session_id: str | None,
                      model: str | None = None, permission_mode: str | None = None) -> SessionDriver:
        project_file = project_store.read_project_file(root) or {}
        proj_settings = project_file.get("settings", {})
        holder: dict[str, SessionDriver] = {}

        async def can_use_tool(tool_name: str, tool_input: dict[str, Any], context: Any):
            d = holder.get("driver")
            return await self._request_permission(
                d.session_id if d else None, tool_name, tool_input, context
            )

        def factory(resume_sid: str | None) -> RunnerSpec:
            return RunnerSpec(
                cwd=root,
                resume=resume_sid,
                setting_sources=["user", "project", "local"],
                permission_mode=permission_mode or proj_settings.get("permission_mode") or "acceptEdits",
                model=model or proj_settings.get("model"),
                extra_options={"can_use_tool": can_use_tool},
            )

        def status_cb(d: SessionDriver) -> None:
            if not d.session_id:
                return
            status = "running" if (d.state == "running" or d.queue_len > 0) else "idle"
            self._bus.publish(
                "sidebar",
                "session_status",
                {
                    "project_id": project_id,
                    "session_id": d.session_id,
                    "status": status,
                    "queue_len": d.queue_len,
                },
            )

        driver = SessionDriver(
            self._runner,
            factory,
            self._bus,
            topic=None,
            hold_open=False,
            session_id=session_id,
            cache=self._cache,
            status_cb=status_cb,
            on_burst_start=self._burst_started,
            on_burst_end=lambda sid: self._burst_ended(sid, project_id, root),
        )
        holder["driver"] = driver
        return driver

    def _register(self, sid: str, driver: SessionDriver, project_id: str) -> None:
        self._drivers[sid] = driver
        self._projects_of[sid] = project_id

    def _burst_started(self, sid: str) -> None:
        # Suppress the watcher AND stamp "Orchid is driving this" immediately, so a
        # follow-up prompt arriving right after turn_completed (but before the burst
        # finishes closing) isn't misread as external terminal activity.
        self._watcher.suppress(sid)
        self._last_burst_end[sid] = time.monotonic()

    def _burst_ended(self, sid: str, project_id: str, root: Path) -> None:
        self._last_burst_end[sid] = time.monotonic()

        async def resync() -> None:
            await asyncio.sleep(POST_BURST_GRACE_S)
            self._watcher.unsuppress(sid)
            try:
                await self._sessions.refresh_from_disk(sid, project_id, root)
            except Exception:
                log.debug("post-burst resync failed for %s", sid, exc_info=True)

        task = asyncio.create_task(resync())
        self._resync_tasks.add(task)
        task.add_done_callback(self._resync_tasks.discard)

    # -- operations -----------------------------------------------------------

    async def create_session(self, project: dict, prompt: str,
                             model: str | None = None, permission_mode: str | None = None) -> str:
        root = Path(project["root"])
        driver = self._build_driver(root, project["id"], session_id=None,
                                    model=model, permission_mode=permission_mode)
        await driver.prompt(prompt)
        try:
            sid = await driver.wait_session_id(30.0)
        except asyncio.TimeoutError:
            await driver.aclose()
            raise ApiError("SESSION_START_TIMEOUT", "claude did not start within 30s", 504)
        self._register(sid, driver, project["id"])
        project_store.set_session_flags(root, sid, created_by="orchid")
        return sid

    async def prompt(self, session_id: str, text: str, force: bool = False) -> dict[str, Any]:
        driver = self._drivers.get(session_id)
        if driver and (driver.state == "running" or driver.queue_len > 0):
            await driver.prompt(text)
            return {"state": "running", "queue_len": driver.queue_len}

        entry, info = await self._sessions.locate(session_id)
        if not force and self._looks_external(session_id, info):
            raise ApiError(
                "EXTERNAL_ACTIVITY",
                "session transcript changed recently outside Orchid (open in a terminal?)",
                409,
            )
        if driver is None:
            driver = self._build_driver(Path(entry["root"]), entry["id"], session_id=session_id)
            self._register(session_id, driver, entry["id"])
        await driver.prompt(text)
        return {"state": "starting", "queue_len": driver.queue_len}

    def _looks_external(self, session_id: str, info: Any) -> bool:
        age = age_seconds(info.last_modified)
        if age is None or age >= self._settings.external_window_s:
            return False
        last_ours = self._last_burst_end.get(session_id)
        if last_ours is not None and (time.monotonic() - last_ours) < self._settings.external_window_s:
            return False  # the recent writer was us
        return True

    async def interrupt(self, session_id: str) -> None:
        driver = self._drivers.get(session_id)
        if not driver or driver.state != "running":
            raise ApiError("NOT_RUNNING", "no turn in flight for this session", 409)
        self._deny_pending(session_id, "interrupted from Orchid")
        await driver.interrupt()

    # -- permissions ----------------------------------------------------------

    async def _request_permission(self, session_id: str | None, tool_name: str,
                                  tool_input: dict[str, Any], context: Any):
        request_id = uuidlib.uuid4().hex
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._perms[request_id] = (fut, session_id)
        preview, _ = _preview(tool_input)
        if session_id:
            self._bus.publish(
                f"session:{session_id}",
                "permission_request",
                {
                    "request_id": request_id,
                    "tool_name": tool_name,
                    "input_preview": preview,
                    "display_name": getattr(context, "display_name", None),
                    "description": getattr(context, "description", None),
                    "expires_at": (
                        datetime.now(timezone.utc) + timedelta(seconds=PERMISSION_TIMEOUT_S)
                    ).isoformat(),
                },
            )
        try:
            behavior, message = await asyncio.wait_for(fut, PERMISSION_TIMEOUT_S)
        except asyncio.TimeoutError:
            behavior, message = "deny", "timed out waiting for approval in Orchid"
        finally:
            self._perms.pop(request_id, None)
        if behavior == "allow":
            return PermissionResultAllow()
        return PermissionResultDeny(message=message or "denied from Orchid")

    async def resolve_permission(self, request_id: str, behavior: str, message: str | None = None) -> None:
        entry = self._perms.get(request_id)
        if entry is None or entry[0].done():
            raise ApiError("PERMISSION_GONE", "permission request expired or already resolved", 410)
        entry[0].set_result((behavior, message))

    def _deny_pending(self, session_id: str, message: str) -> None:
        for request_id, (fut, sid) in list(self._perms.items()):
            if sid == session_id and not fut.done():
                fut.set_result(("deny", message))

    # -- lifecycle ------------------------------------------------------------

    async def aclose(self) -> None:
        for task in list(self._resync_tasks):
            task.cancel()
        for sid, driver in list(self._drivers.items()):
            self._deny_pending(sid, "orchid is shutting down")
            try:
                await driver.interrupt()
            except Exception:
                pass
        await asyncio.sleep(0)  # let interrupts land
        results = await asyncio.gather(
            *(d.aclose() for d in self._drivers.values()), return_exceptions=True
        )
        for r in results:
            if isinstance(r, Exception):
                log.warning("driver close error: %s", r)
        self._drivers.clear()
