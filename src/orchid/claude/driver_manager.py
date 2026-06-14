import asyncio
import logging
import time
import uuid as uuidlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from claude_agent_sdk import HookMatcher, PermissionResultAllow, PermissionResultDeny

from ..bus import EventBus
from ..config import Settings
from ..services import ApiError, SessionService
from ..store import project_store, usage_store
from ..watch.watcher import WatcherManager
from . import roles
from .catalog import age_seconds
from .driver import SessionDriver
from .elevated_tools import ELEVATED_SERVER, ELEVATED_TOOL_NAMES, build_elevated_server
from .git_tools import GIT_SERVER, GIT_TOOL_NAMES, build_git_server
from .planning import PLAN_SERVER, PLAN_TOOL_NAMES, build_plan_server
from .runner import Runner, RunnerSpec
from .transcript import TranscriptCache, _preview

log = logging.getLogger(__name__)

PERMISSION_TIMEOUT_S = 300.0
POST_BURST_GRACE_S = 2.0

# Provably read-only tools auto-approved without prompting: they cannot mutate
# state, so gating them only burns the approval window on diagnostics. Kept
# deliberately narrow — only tools that are read-only by construction. Bash is
# NOT here (it is a general shell); agents should use Grep/Read/Glob, which are.
# Privileged content reads (elevated_read_file) stay gated; elevated_stat is
# metadata-only and safe.
READ_ONLY_TOOLS = frozenset({
    "Read", "Grep", "Glob", "NotebookRead",
    "mcp__orchid_git__git_status",
    "mcp__orchid_git__git_diff",
    "mcp__orchid_elevated__elevated_stat",
})


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
        orchidd_client=None,
    ):
        self._runner = runner
        self._bus = bus
        self._cache = cache
        self._sessions = sessions
        self._watcher = watcher
        self._settings = settings
        self._orchidd = orchidd_client
        self._drivers: dict[str, SessionDriver] = {}
        self._projects_of: dict[str, str] = {}  # sid -> project_id
        self._roots_of: dict[str, Path] = {}  # sid -> project root
        self._perms: dict[str, tuple[asyncio.Future, str | None, dict]] = {}
        self._last_burst_end: dict[str, float] = {}
        self._resync_tasks: set[asyncio.Task] = set()
        self._agents: dict[str, dict[str, str]] = {}  # sid -> {agent_id: status}

    # -- status -------------------------------------------------------------

    def is_running(self, session_id: str) -> bool:
        d = self._drivers.get(session_id)
        return bool(d and (d.state == "running" or d.queue_len > 0))

    def queue_len(self, session_id: str) -> int:
        d = self._drivers.get(session_id)
        return d.queue_len if d else 0

    def live_agents(self, session_id: str) -> dict[str, str]:
        return dict(self._agents.get(session_id, {}))

    def active_sessions_for_project(self, project_id: str) -> list[str]:
        return [
            sid for sid, pid in self._projects_of.items()
            if pid == project_id and self.is_running(sid)
        ]

    def all_active_projects(self) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for sid, pid in self._projects_of.items():
            if sid in self._drivers:
                result.setdefault(pid, []).append(sid)
        return result

    # -- subagent hooks -------------------------------------------------------

    def _subagent_hooks(self):
        async def on_start(input_data: dict, _tool_use_id: str | None, _ctx: Any):
            sid, aid = input_data.get("session_id"), input_data.get("agent_id")
            if sid and aid:
                self._agents.setdefault(sid, {})[aid] = "running"
                self._bus.publish(
                    f"session:{sid}",
                    "agent_started",
                    {"agent_id": aid, "agent_type": input_data.get("agent_type")},
                )
            return {}

        async def on_stop(input_data: dict, _tool_use_id: str | None, _ctx: Any):
            sid, aid = input_data.get("session_id"), input_data.get("agent_id")
            if sid and aid:
                self._agents.setdefault(sid, {})[aid] = "done"
                self._bus.publish(f"session:{sid}", "agent_stopped", {"agent_id": aid})
            return {}

        return {
            "SubagentStart": [HookMatcher(hooks=[on_start])],
            "SubagentStop": [HookMatcher(hooks=[on_stop])],
        }

    # -- driver construction --------------------------------------------------

    def _build_driver(self, root: Path, project_id: str, *, session_id: str | None,
                      model: str | None = None, permission_mode: str | None = None,
                      system_prompt: Any = None, agents: dict[str, Any] | None = None,
                      mcp_servers: dict[str, Any] | None = None,
                      allowed_tools: list[str] | None = None,
                      consult: bool = False) -> SessionDriver:
        project_file = project_store.read_project_file(root) or {}
        proj_settings = project_file.get("settings", {})
        holder: dict[str, SessionDriver] = {}

        effective_mcp = dict(mcp_servers) if mcp_servers else {}
        effective_allowed = list(allowed_tools) if allowed_tools else []
        if self._orchidd:
            elevated_server = build_elevated_server(self._orchidd)
            effective_mcp[ELEVATED_SERVER] = elevated_server
            effective_allowed.extend(ELEVATED_TOOL_NAMES)
        if consult:
            from .consult import CONSULT_SERVER, CONSULT_TOOL_NAMES, build_consult_server
            consult_server = build_consult_server(
                dm=self, registry=self._sessions._registry,
                bus=self._bus, caller_holder=holder,
            )
            effective_mcp[CONSULT_SERVER] = consult_server
            effective_allowed.extend(CONSULT_TOOL_NAMES)

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
                system_prompt=system_prompt,
                agents=agents,
                mcp_servers=effective_mcp or None,
                allowed_tools=effective_allowed or None,
                disallowed_tools=["AskUserQuestion"],
                extra_options={"can_use_tool": can_use_tool, "hooks": self._subagent_hooks()},
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
            on_turn_completed=lambda sid, payload: self._record_usage(sid, project_id, root, payload),
        )
        holder["driver"] = driver
        return driver

    def _register(self, sid: str, driver: SessionDriver, project_id: str, root: Path | None = None) -> None:
        self._drivers[sid] = driver
        self._projects_of[sid] = project_id
        if root is not None:
            self._roots_of[sid] = root

    def _burst_started(self, sid: str) -> None:
        # Suppress the watcher AND stamp "Orchid is driving this" immediately, so a
        # follow-up prompt arriving right after turn_completed (but before the burst
        # finishes closing) isn't misread as external terminal activity.
        self._watcher.suppress(sid)
        self._last_burst_end[sid] = time.monotonic()

    def _record_usage(self, sid: str, project_id: str, root: Path, payload: dict) -> None:
        """Persist the cost/turn data the SDK already reported, and announce the
        new per-session total on the sidebar. Runs inside the driver's own task."""
        if payload.get("total_cost_usd") is None:
            return  # SDK reported no cost for this turn; nothing to accumulate
        totals = usage_store.add_turn(
            root, sid,
            cost_usd=payload.get("total_cost_usd") or 0.0,
            duration_ms=payload.get("duration_ms") or 0,
            is_error=bool(payload.get("is_error")),
        )
        self._bus.publish(
            "sidebar", "usage_updated",
            {"project_id": project_id, "session_id": sid, "usage": totals},
        )

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

    async def create_orchestrator_session(
        self, project: dict, prompt: str, child_roots: list[Path] | None = None,
    ) -> str:
        """Start a session in this project: the enabled roles wired in as subagents,
        the AGENTS.md/goal/roster system prompt, and the plan + git MCP tools. This is
        the one way Orchid starts a session — every session is project-aware. Edits
        auto-apply under the project's permission_mode (acceptEdits by default); risky
        tools still hit the broker."""
        root = Path(project["root"])
        agents, append = roles.assemble_orchestrator(root, child_roots=child_roots)
        plan_server = build_plan_server(root, project["id"], self._bus)
        git_server = build_git_server(root, project["id"], self._bus)
        driver = self._build_driver(
            root, project["id"], session_id=None,
            system_prompt={"type": "preset", "preset": "claude_code", "append": append},
            agents=agents,
            mcp_servers={PLAN_SERVER: plan_server, GIT_SERVER: git_server},
            allowed_tools=PLAN_TOOL_NAMES + GIT_TOOL_NAMES,
            consult=True,
        )
        await driver.prompt(prompt)
        try:
            sid = await driver.wait_session_id(30.0)
        except asyncio.TimeoutError:
            await driver.aclose()
            raise ApiError("SESSION_START_TIMEOUT", "claude did not start within 30s", 504)
        self._register(sid, driver, project["id"], root)
        project_store.set_session_flags(root, sid, created_by="orchid", role="orchestrator")
        return sid

    async def prompt(self, session_id: str, text: str, force: bool = False) -> dict[str, Any]:
        driver = self._drivers.get(session_id)
        if driver and (driver.state == "running" or driver.queue_len > 0):
            await driver.prompt(text)
            return {"state": "running", "queue_len": driver.queue_len}

        entry, info = await self._sessions.locate(session_id)
        root = Path(entry["root"])
        if not force and self._terminal_owned(session_id, info, root, driver):
            raise ApiError(
                "EXTERNAL_ACTIVITY",
                "this session is owned by a terminal (or changed recently outside Orchid); "
                "driving it from the web can corrupt it — take over only if no terminal is using it",
                409,
            )
        if driver is None:
            driver = self._build_driver(root, entry["id"], session_id=session_id)
            self._register(session_id, driver, entry["id"], root)
        await driver.prompt(text)
        return {"state": "starting", "queue_len": driver.queue_len}

    def _terminal_owned(self, session_id: str, info: Any, root: Path, driver) -> bool:
        """Would driving this session from the web risk a two-writer conflict?

        Two writers on one Claude Code transcript corrupt it, and there is no
        lock to detect a live-but-idle terminal session. So we are conservative:
        a session Orchid did not create is assumed terminal-owned until the user
        explicitly takes it over (force) — mtime-independent, because an idle
        terminal session (waiting at its prompt) has a stale mtime yet is very
        much alive. Once Orchid has a driver for it, only a *fresh* outside write
        (mtime since our last burst) re-raises the guard.
        """
        if driver is not None:
            return self._looks_external(session_id, info)
        flags = project_store.get_session_flags(root).get(session_id, {})
        if flags.get("created_by") != "orchid":
            return True
        return self._looks_external(session_id, info)

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
        if tool_name in READ_ONLY_TOOLS:
            return PermissionResultAllow()  # read-only: never prompt, never time out
        request_id = uuidlib.uuid4().hex
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        preview, _ = _preview(tool_input)
        payload = {
            "request_id": request_id,
            "tool_name": tool_name,
            "input_preview": preview,
            "display_name": getattr(context, "display_name", None),
            "description": getattr(context, "description", None),
            "expires_at": (
                datetime.now(timezone.utc) + timedelta(seconds=PERMISSION_TIMEOUT_S)
            ).isoformat(),
        }
        self._perms[request_id] = (fut, session_id, payload)
        if session_id:
            self._bus.publish(f"session:{session_id}", "permission_request", payload)
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

    def pending_permissions(self, session_id: str) -> list[dict]:
        return [
            payload
            for _rid, (fut, sid, payload) in self._perms.items()
            if sid == session_id and not fut.done()
        ]

    def _deny_pending(self, session_id: str, message: str) -> None:
        for request_id, (fut, sid, _payload) in list(self._perms.items()):
            if sid == session_id and not fut.done():
                fut.set_result(("deny", message))

    # -- lifecycle ------------------------------------------------------------

    def _running_sessions_path(self) -> Path:
        return self._settings.orchid_home / "running_sessions.json"

    def _persist_running(self) -> None:
        """Save the set of in-flight sessions so a restart can resume them."""
        running = {}
        for sid, d in self._drivers.items():
            pid = self._projects_of.get(sid)
            root = self._roots_of.get(sid)
            if (d.state == "running" or d.queue_len > 0) and pid and root:
                running[sid] = {"project_id": pid, "root": str(root)}
        if running:
            from ..store.jsonio import atomic_write_json
            atomic_write_json(self._running_sessions_path(), running)
        else:
            self._running_sessions_path().unlink(missing_ok=True)

    async def auto_resume(self) -> None:
        """Reconnect drivers for sessions that were running before the last shutdown."""
        path = self._running_sessions_path()
        if not path.exists():
            return
        from ..store.jsonio import load_json
        running: dict[str, dict] = load_json(path, default={})
        path.unlink(missing_ok=True)
        if not running:
            return
        for sid, info in running.items():
            try:
                root = Path(info["root"])
                project_id = info["project_id"]
                if not root.exists():
                    log.debug("auto-resume: root %s gone, skipping %s", root, sid)
                    continue
                driver = self._build_driver(root, project_id, session_id=sid)
                self._register(sid, driver, project_id, root)
                await driver.prompt("continue")
                log.info("auto-resumed session %s (project %s)", sid, project_id)
            except Exception:
                log.warning("auto-resume failed for %s", sid, exc_info=True)

    async def aclose(self) -> None:
        for task in list(self._resync_tasks):
            task.cancel()
        self._persist_running()
        for sid in list(self._drivers):
            self._deny_pending(sid, "orchid is shutting down")
        results = await asyncio.gather(
            *(d.aclose() for d in self._drivers.values()), return_exceptions=True
        )
        for r in results:
            if isinstance(r, Exception):
                log.warning("driver close error: %s", r)
        self._drivers.clear()
