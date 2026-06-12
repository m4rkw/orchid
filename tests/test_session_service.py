import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from claude_agent_sdk import SDKSessionInfo, SessionMessage

from orchid.bus import EventBus
from orchid.claude.catalog import Catalog
from orchid.claude.transcript import TranscriptCache
from orchid.services import ApiError, SessionService, status_from_updated
from orchid.store.registry import Registry

pytestmark = pytest.mark.asyncio

SID = "11111111-2222-3333-4444-555555555555"


def make_info(sid=SID, cwd="/tmp/p", minutes_ago=120.0):
    ts = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return SDKSessionInfo(
        session_id=sid,
        summary="A session",
        last_modified=ts,
        file_size=10,
        custom_title=None,
        first_prompt="hello",
        git_branch="main",
        cwd=cwd,
        tag=None,
        created_at=ts,
    )


def make_records(n=3, sid=SID):
    return [
        SessionMessage(
            type="user" if i % 2 == 0 else "assistant",
            uuid=f"u{i}",
            session_id=sid,
            message={"role": "user", "content": f"msg {i}"},
            parent_tool_use_id=None,
        )
        for i in range(n)
    ]


@pytest.fixture
def harness(settings, homes):
    root = homes.tmp / "proj"
    root.mkdir()
    registry = Registry(settings.registry_path)
    registry.add("prj_1", root)
    catalog = Catalog()
    calls = {"info": 0, "messages": 0}

    async def session_info(sid, r, _root=root):
        calls["info"] += 1
        return make_info(sid) if sid == SID and Path(r) == root else None

    async def session_messages(sid, r):
        calls["messages"] += 1
        return make_records() if sid == SID else []

    async def subagents(sid, r):
        return ["agent-a1"] if sid == SID else []

    async def subagent_messages(sid, aid, r):
        return make_records(2)

    catalog.session_info = session_info
    catalog.session_messages = session_messages
    catalog.subagents = subagents
    catalog.subagent_messages = subagent_messages
    bus = EventBus()
    service = SessionService(registry, catalog, TranscriptCache(), bus, settings)
    return service, bus, calls, root


async def test_locate_unknown_404(harness):
    service, *_ = harness
    with pytest.raises(ApiError) as e:
        await service.locate("nope")
    assert e.value.status == 404


async def test_detail_includes_handoff(harness):
    service, _bus, _calls, root = harness
    detail = await service.detail(SID)
    assert detail.project_id == "prj_1"
    assert detail.handoff_command == f"cd {root} && claude --resume {SID}"
    assert detail.title == "A session"
    assert detail.status == "idle"  # 2h old


async def test_messages_load_once_and_seq(harness):
    service, bus, calls, _root = harness
    out = await service.messages(SID)
    assert [m["uuid"] for m in out["messages"]] == ["u0", "u1", "u2"]
    assert out["seq"] == 0
    first_reads = calls["messages"]
    await service.messages(SID)
    assert calls["messages"] == first_reads  # cache hit, no disk re-read
    bus.publish(f"session:{SID}", "message", {})
    assert (await service.messages(SID))["seq"] == 1


async def test_full_message_and_missing(harness):
    service, *_ = harness
    full = await service.full_message(SID, "u1")
    assert full.uuid == "u1"
    with pytest.raises(ApiError):
        await service.full_message(SID, "ghost")


async def test_agents_with_counts(harness):
    service, *_ = harness
    agents = await service.agents(SID)
    assert agents[0].agent_id == "agent-a1"
    assert agents[0].message_count == 2
    tagged = await service.agent_messages(SID, "agent-a1")
    assert all(m["agent_id"] == "agent-a1" for m in tagged["messages"])


async def test_refresh_publishes_deltas_after_first_load(harness):
    service, bus, _calls, root = harness
    sub = bus.subscribe({f"session:{SID}"})
    await service.refresh_from_disk(SID, "prj_1", root)  # first load: no message spam
    types = [sub.queue.get_nowait()["type"] for _ in range(sub.queue.qsize())]
    assert types == ["session_upserted"]
    # disk grows by one record
    service._catalog.session_messages = _grown(make_records(4))
    await service.refresh_from_disk(SID, "prj_1", root)
    events = [sub.queue.get_nowait() for _ in range(sub.queue.qsize())]
    msg_events = [e for e in events if e["type"] == "message"]
    assert len(msg_events) == 1 and msg_events[0]["payload"]["message"]["uuid"] == "u3"
    assert any(e["type"] == "session_upserted" for e in events)


def _grown(records):
    async def session_messages(sid, r):
        return records

    return session_messages


async def test_status_window():
    now = datetime.now(timezone.utc)
    assert status_from_updated((now - timedelta(seconds=10)).isoformat(), 45) == "external"
    assert status_from_updated((now - timedelta(seconds=90)).isoformat(), 45) == "idle"
    assert status_from_updated(None, 45) == "idle"
    assert status_from_updated("garbage", 45) == "idle"
