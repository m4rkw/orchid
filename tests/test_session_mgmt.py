from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from claude_agent_sdk import SDKSessionInfo

from orchid.bus import EventBus
from orchid.claude.catalog import Catalog
from orchid.claude.transcript import TranscriptCache
from orchid.services import ApiError, SessionService
from orchid.store import project_store
from orchid.store.registry import Registry

pytestmark = pytest.mark.asyncio

SID = "abcabcab-1111-2222-3333-444444444444"


def make_info(sid=SID, cwd="", minutes_ago=120.0, title=None):
    ts = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return SDKSessionInfo(
        session_id=sid, summary="s", last_modified=ts, file_size=1, custom_title=title,
        first_prompt="p", git_branch=None, cwd=cwd, tag=None, created_at=ts,
    )


@pytest.fixture
def harness(settings, homes):
    root = homes.tmp / "mgmt"
    root.mkdir()
    project_store.init_project(root, "prj_m", "Mgmt")
    registry = Registry(settings.registry_path)
    registry.add("prj_m", root)
    catalog = Catalog()
    state = {"title": None, "age": 120.0, "deleted": False, "forked_from": None}

    async def session_info(sid, r):
        if sid == SID and not state["deleted"]:
            return make_info(sid, str(root), state["age"], state["title"])
        if sid == "fork-new":
            return make_info("fork-new", str(root), 0.1)
        return None

    async def rename(sid, title, r):
        state["title"] = title

    async def delete(sid, r):
        state["deleted"] = True

    async def fork(sid, r, title=None):
        state["forked_from"] = sid
        return "fork-new"

    catalog.session_info = session_info
    catalog.rename = rename
    catalog.delete = delete
    catalog.fork = fork
    bus = EventBus()
    service = SessionService(registry, catalog, TranscriptCache(), bus, settings)
    return service, bus, state, root


async def test_rename_calls_sdk_and_upserts(harness):
    service, bus, state, _root = harness
    sub = bus.subscribe()
    await service.rename(SID, "My Title")
    assert state["title"] == "My Title"
    evt = sub.queue.get_nowait()
    assert evt["type"] == "session_upserted"
    assert evt["payload"]["session"]["title"] == "My Title"


async def test_pin_and_archive_flags(harness):
    service, _bus, _state, root = harness
    await service.set_flag(SID, pinned=True)
    assert project_store.get_session_flags(root)[SID]["pinned"] is True
    await service.set_flag(SID, archived=True)
    flags = project_store.get_session_flags(root)[SID]
    assert flags["archived"] is True and flags["pinned"] is True


async def test_delete_idle_ok(harness):
    service, bus, state, _root = harness
    sub = bus.subscribe()
    await service.delete(SID)
    assert state["deleted"] is True
    types = [sub.queue.get_nowait()["type"] for _ in range(sub.queue.qsize())]
    assert "session_removed" in types


async def test_delete_refused_when_running(harness):
    service, _bus, _state, _root = harness
    service.is_running = lambda sid: True
    with pytest.raises(ApiError) as e:
        await service.delete(SID)
    assert e.value.status == 409 and e.value.code == "SESSION_RUNNING"


async def test_delete_refused_when_external(harness):
    service, _bus, state, _root = harness
    state["age"] = 0.1  # fresh mtime -> external
    with pytest.raises(ApiError) as e:
        await service.delete(SID)
    assert e.value.code == "EXTERNAL_ACTIVITY"
    await service.delete(SID, force=True)  # force overrides
    assert state["deleted"] is True


async def test_fork_returns_new_sid(harness):
    service, bus, state, _root = harness
    sub = bus.subscribe()
    new_sid = await service.fork(SID, title="branch")
    assert new_sid == "fork-new"
    assert state["forked_from"] == SID
    upserts = [e for _ in range(sub.queue.qsize()) if (e := sub.queue.get_nowait())["type"] == "session_upserted"]
    assert any(u["payload"]["session"]["id"] == "fork-new" for u in upserts)


async def test_live_agents_merge_into_listing(harness):
    service, _bus, _state, root = harness

    async def subagents(sid, r):
        return ["ag-rest"]

    async def subagent_messages(sid, aid, r):
        return [1, 2]

    service._catalog.subagents = subagents
    service._catalog.subagent_messages = subagent_messages
    service.live_agents = lambda sid: {"ag-rest": "running", "ag-live-only": "running"}
    agents = await service.agents(SID)
    by_id = {a.agent_id: a for a in agents}
    assert by_id["ag-rest"].status == "running"  # live status overrides at-rest
    assert by_id["ag-rest"].message_count == 2
    assert "ag-live-only" in by_id  # live-only agent surfaced before its file exists
