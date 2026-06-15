import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from claude_agent_sdk import (
    AssistantMessage,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    SDKSessionInfo,
    SystemMessage,
    TextBlock,
)

import orchid.claude.driver_manager as dm
from orchid.bus import EventBus
from orchid.claude.catalog import Catalog
from orchid.claude.driver_manager import DriverManager
from orchid.claude.consult import CONSULT_TOOL_NAMES
from orchid.claude.planning import PLAN_TOOL_NAMES
from orchid.claude.transcript import TranscriptCache
from orchid.services import ApiError, SessionService
from orchid.store import project_store
from orchid.store.registry import Registry
from orchid.watch.watcher import WatcherManager

pytestmark = pytest.mark.asyncio

SID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def init_msg(sid=SID):
    return SystemMessage(subtype="init", data={"session_id": sid})


def text_msg(text="hi"):
    return AssistantMessage(content=[TextBlock(text=text)], model="m")


def result_msg(sid=SID):
    return ResultMessage(
        subtype="success", duration_ms=50, duration_api_ms=40, is_error=False,
        num_turns=1, session_id=sid, total_cost_usd=0.02,
    )


def make_info(sid=SID, cwd="", minutes_ago=120.0):
    ts = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return SDKSessionInfo(
        session_id=sid, summary="s", last_modified=ts, file_size=1, custom_title=None,
        first_prompt="p", git_branch=None, cwd=cwd, tag=None, created_at=ts,
    )


class Harness:
    def __init__(self, settings, homes, runner):
        self.root = homes.tmp / "drv"
        self.root.mkdir(exist_ok=True)
        project_store.init_project(self.root, "prj_d", "Drv")
        self.registry = Registry(settings.registry_path)
        self.entry = self.registry.add("prj_d", self.root)
        self.bus = EventBus()
        self.cache = TranscriptCache()
        self.catalog = Catalog()
        self.info_age_minutes = 120.0

        async def session_info(sid, r):
            return make_info(sid, str(self.root), self.info_age_minutes) if sid == SID else None

        async def session_messages(sid, r):
            return []

        self.catalog.session_info = session_info
        self.catalog.session_messages = session_messages
        self.sessions = SessionService(self.registry, self.catalog, self.cache, self.bus, settings)
        self.watcher = WatcherManager(self.catalog, self.sessions, settings)
        self.manager = DriverManager(runner, self.bus, self.cache, self.sessions, self.watcher, settings)
        self.sessions.is_running = self.manager.is_running


@pytest.fixture
def harness(settings, homes, fake_runner):
    def make(scripts):
        return Harness(settings, homes, fake_runner(scripts))

    return make


async def wait_for(predicate, timeout=3.0):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)


async def test_create_session_returns_sid_and_caches(harness):
    h = harness([[[init_msg(), text_msg("made it"), result_msg()]]])
    sid = await h.manager.create_orchestrator_session(h.entry, "build me a thing")
    assert sid == SID
    # live messages were cached under the real sid (pending-topic flush worked)
    await wait_for(lambda: h.cache.message_count(SID) == 1)
    assert h.bus.current_seq(f"session:{SID}") >= 2  # turn_started + message (+ completed)
    flags = project_store.get_session_flags(h.root)
    assert flags[SID]["created_by"] == "orchid"
    await h.manager.aclose()


async def test_create_orchestrator_session_wires_roles_and_plan_tools(harness):
    h = harness([[[init_msg(), text_msg("planning"), result_msg()]]])
    (h.root / "AGENTS.md").write_text("# Drv\nBuild: uv run pytest")
    pf = project_store.read_project_file(h.root)
    pf["intent"], pf["goal"] = "goal", "users can sign up and track vehicles"
    project_store.write_project_file(h.root, pf)
    sid = await h.manager.create_orchestrator_session(h.entry, "plan milestones")
    assert sid == SID

    spec, _client = h.manager._runner.opened[0]
    assert set(spec.agents) == {"worker", "reviewer", "verifier"}
    assert spec.permission_mode == "acceptEdits"  # falls back to project setting
    assert spec.mcp_servers and "orchid_plan" in spec.mcp_servers
    assert spec.mcp_servers and "orchid_git" in spec.mcp_servers
    assert spec.mcp_servers and "orchid_spec" in spec.mcp_servers
    from orchid.claude.git_tools import GIT_TOOL_NAMES
    from orchid.claude.spec_tools import SPEC_TOOL_NAMES
    assert spec.allowed_tools == PLAN_TOOL_NAMES + GIT_TOOL_NAMES + SPEC_TOOL_NAMES + CONSULT_TOOL_NAMES
    sp = spec.system_prompt
    assert sp["type"] == "preset" and sp["preset"] == "claude_code"
    assert "orchestrator for this project" in sp["append"]
    assert "uv run pytest" in sp["append"]  # AGENTS.md embedded in the prompt
    assert "users can sign up and track vehicles" in sp["append"]  # project goal anchors it
    flags = project_store.get_session_flags(h.root).get(SID, {})
    assert flags["created_by"] == "orchid" and flags["role"] == "orchestrator"
    await h.manager.aclose()


async def test_read_only_tools_auto_approved(harness):
    h = harness([])
    for name in ("Read", "Grep", "Glob", "mcp__orchid_git__git_diff",
                 "mcp__orchid_elevated__elevated_stat"):
        result = await h.manager._request_permission(SID, name, {}, None)
        assert isinstance(result, PermissionResultAllow)
    # Never entered the broker: no pending request, so no 300s window to burn.
    assert h.manager.pending_permissions(SID) == []


async def test_write_tools_still_gated(harness):
    h = harness([])
    task = asyncio.create_task(
        h.manager._request_permission(SID, "Bash", {"command": "ls"}, None)
    )
    await wait_for(lambda: len(h.manager.pending_permissions(SID)) == 1)
    rid = h.manager.pending_permissions(SID)[0]["request_id"]
    await h.manager.resolve_permission(rid, "allow")
    assert isinstance(await task, PermissionResultAllow)
    await h.manager.aclose()


class _FakeNotifier:
    def __init__(self):
        self.pushes = []

    def session_url(self, pid, sid):
        return f"u/{pid}/{sid}"

    def push_bg(self, title, message, url=None, url_title=None):
        self.pushes.append((title, message, url))


async def test_permission_request_pushes_once_per_burst(harness):
    h = harness([])
    fake = _FakeNotifier()
    h.manager._notifier = fake
    h.manager._projects_of[SID] = "prj_d"

    t1 = asyncio.create_task(h.manager._request_permission(SID, "Bash", {"command": "ls"}, None))
    await wait_for(lambda: len(h.manager.pending_permissions(SID)) == 1)
    # A second concurrent request in the same burst must NOT fire another push.
    t2 = asyncio.create_task(h.manager._request_permission(SID, "Write", {}, None))
    await wait_for(lambda: len(h.manager.pending_permissions(SID)) == 2)

    assert len(fake.pushes) == 1  # push_bg called synchronously, once
    assert fake.pushes[0][2] == f"u/prj_d/{SID}"

    for p in list(h.manager.pending_permissions(SID)):
        await h.manager.resolve_permission(p["request_id"], "allow")
    await t1
    await t2
    await h.manager.aclose()


async def test_read_only_request_does_not_push(harness):
    h = harness([])
    fake = _FakeNotifier()
    h.manager._notifier = fake
    await h.manager._request_permission(SID, "Grep", {}, None)
    assert fake.pushes == []  # auto-allowed before the broker / notifier


async def test_create_session_timeout_504(harness, monkeypatch):
    gate = asyncio.Event()  # stream yields nothing, blocks forever
    h = harness([[[gate]]])

    async def fast_wait(self, timeout=30.0):
        return await asyncio.wait_for(self._sid_event.wait(), 0.1)

    monkeypatch.setattr("orchid.claude.driver.SessionDriver.wait_session_id", fast_wait)
    with pytest.raises(ApiError) as e:
        await h.manager.create_orchestrator_session(h.entry, "hello?")
    assert e.value.status == 504


async def test_prompt_external_guard_and_force(harness):
    h = harness([[[init_msg(), result_msg()]]])
    h.info_age_minutes = 0.0  # file touched seconds ago by someone else
    with pytest.raises(ApiError) as e:
        await h.manager.prompt(SID, "hi")
    assert e.value.status == 409 and e.value.code == "EXTERNAL_ACTIVITY"

    out = await h.manager.prompt(SID, "hi", force=True)
    assert out["state"] == "starting"
    await wait_for(lambda: not h.manager.is_running(SID))
    await h.manager.aclose()


async def test_terminal_owned_session_requires_takeover(harness):
    # The real-world bug: an idle terminal session (stale mtime) is still alive.
    # A session Orchid did not create must require an explicit takeover regardless
    # of mtime, so the web can't accidentally spawn a second writer on it.
    h = harness([[[init_msg(), result_msg()]]])
    h.info_age_minutes = 999.0  # not recently written — old, looks idle
    assert project_store.get_session_flags(h.root).get(SID, {}).get("created_by") != "orchid"
    with pytest.raises(ApiError) as e:
        await h.manager.prompt(SID, "hi")  # blocked despite stale mtime
    assert e.value.code == "EXTERNAL_ACTIVITY"
    out = await h.manager.prompt(SID, "hi", force=True)  # explicit takeover works
    assert out["state"] == "starting"
    await wait_for(lambda: not h.manager.is_running(SID))
    await h.manager.aclose()


async def test_burst_start_marks_session_ours(harness):
    # Regression: a follow-up prompt can arrive after turn_completed but before the
    # burst finishes closing. Stamping at burst start must already suppress the
    # external false-positive, even with a fresh file mtime.
    h = harness([])
    fresh = make_info(minutes_ago=0.0)
    assert h.manager._looks_external(SID, fresh) is True  # unknown session + fresh mtime
    h.manager._burst_started(SID)
    assert h.manager._looks_external(SID, fresh) is False  # now recognized as ours


async def test_own_recent_burst_not_external(harness):
    h = harness([[[init_msg(), result_msg()]], [[result_msg()]]])
    project_store.set_session_flags(h.root, SID, created_by="orchid")  # Orchid owns it
    h.info_age_minutes = 120.0
    await h.manager.prompt(SID, "one")
    await wait_for(lambda: not h.manager.is_running(SID))
    h.info_age_minutes = 0.0  # mtime is fresh — but the writer was us
    out = await h.manager.prompt(SID, "two")  # no force needed
    assert out["state"] in ("starting", "running")
    await wait_for(lambda: not h.manager.is_running(SID))
    await h.manager.aclose()


async def test_queue_while_running_and_interrupt(harness):
    gate = asyncio.Event()
    h = harness([[[init_msg(), gate, result_msg()]]])
    await h.manager.prompt(SID, "long task", force=True)
    await wait_for(lambda: (d := h.manager._drivers.get(SID)) is not None and d.state == "running")

    out = await h.manager.prompt(SID, "queued one")
    assert out == {"state": "running", "queue_len": 1}

    await h.manager.interrupt(SID)  # sets the gate via FakeClient.interrupt
    await wait_for(lambda: not h.manager.is_running(SID))
    assert h.manager.queue_len(SID) == 0

    with pytest.raises(ApiError) as e:
        await h.manager.interrupt(SID)
    assert e.value.status == 409
    await h.manager.aclose()


async def test_status_events_on_sidebar(harness):
    h = harness([[[init_msg(), result_msg()]]])
    project_store.set_session_flags(h.root, SID, created_by="orchid")  # Orchid owns it
    sub = h.bus.subscribe()
    await h.manager.prompt(SID, "go", force=False)
    await wait_for(lambda: not h.manager.is_running(SID))
    events = []
    while sub.queue.qsize():
        evt = sub.queue.get_nowait()
        if evt["type"] == "session_status":
            events.append((evt["payload"]["status"], evt["payload"]["session_id"]))
    assert ("running", SID) in events
    assert events[-1][0] == "idle"
    await h.manager.aclose()


async def test_permission_roundtrip(harness):
    h = harness([])
    sub = h.bus.subscribe({f"session:{SID}"})

    task = asyncio.create_task(
        h.manager._request_permission(SID, "Bash", {"command": "rm -rf /tmp/x"}, None)
    )
    await wait_for(lambda: sub.queue.qsize() > 0)
    evt = sub.queue.get_nowait()
    assert evt["type"] == "permission_request"
    payload = evt["payload"]
    assert payload["tool_name"] == "Bash"
    assert "rm -rf" in payload["input_preview"]

    await h.manager.resolve_permission(payload["request_id"], "allow")
    assert isinstance(await task, PermissionResultAllow)

    with pytest.raises(ApiError) as e:
        await h.manager.resolve_permission(payload["request_id"], "allow")
    assert e.value.status == 410


async def test_permission_deny_and_timeout(harness, monkeypatch):
    h = harness([])
    sub = h.bus.subscribe({f"session:{SID}"})
    task = asyncio.create_task(h.manager._request_permission(SID, "Write", {}, None))
    await wait_for(lambda: sub.queue.qsize() > 0)
    rid = sub.queue.get_nowait()["payload"]["request_id"]
    await h.manager.resolve_permission(rid, "deny", "nope")
    result = await task
    assert isinstance(result, PermissionResultDeny) and result.message == "nope"

    monkeypatch.setattr(dm, "PERMISSION_TIMEOUT_S", 0.05)
    result = await h.manager._request_permission(SID, "Write", {}, None)
    assert isinstance(result, PermissionResultDeny)
    assert "timed out" in result.message


async def test_subagent_hooks_track_live_agents(harness):
    h = harness([])
    hooks = h.manager._subagent_hooks()
    on_start = hooks["SubagentStart"][0].hooks[0]
    on_stop = hooks["SubagentStop"][0].hooks[0]
    sub = h.bus.subscribe({f"session:{SID}"})

    await on_start({"session_id": SID, "agent_id": "ag-1", "agent_type": "explorer"}, None, None)
    assert h.manager.live_agents(SID) == {"ag-1": "running"}
    evt = sub.queue.get_nowait()
    assert evt["type"] == "agent_started"
    assert evt["payload"] == {"agent_id": "ag-1", "agent_type": "explorer"}

    await on_stop({"session_id": SID, "agent_id": "ag-1"}, None, None)
    assert h.manager.live_agents(SID) == {"ag-1": "done"}
    assert sub.queue.get_nowait()["type"] == "agent_stopped"


async def test_interrupt_denies_pending_permissions(harness):
    gate = asyncio.Event()
    h = harness([[[init_msg(), gate, result_msg()]]])
    await h.manager.prompt(SID, "task", force=True)
    await wait_for(lambda: h.manager.is_running(SID))
    task = asyncio.create_task(h.manager._request_permission(SID, "Bash", {}, None))
    await asyncio.sleep(0.05)
    await h.manager.interrupt(SID)
    result = await task
    assert isinstance(result, PermissionResultDeny)
    await h.manager.aclose()
