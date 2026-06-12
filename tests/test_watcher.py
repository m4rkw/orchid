import asyncio
from pathlib import Path

import pytest
from claude_agent_sdk import project_key_for_directory

from orchid.claude.catalog import Catalog
from orchid.config import Settings
from orchid.watch.watcher import WatcherManager

pytestmark = pytest.mark.asyncio


class FakeSessions:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    async def refresh_from_disk(self, sid: str, pid: str, root: Path) -> None:
        self.calls.append((sid, pid))


@pytest.fixture
async def manager(homes, settings):
    root = homes.tmp / "watched"
    root.mkdir()
    sessions = FakeSessions()
    m = WatcherManager(Catalog(), sessions, settings)
    await m._register("prj_w", root)
    key = project_key_for_directory(str(root))
    base = settings.claude_config_dir / "projects"
    yield m, sessions, base, key
    await m.aclose()


async def test_handle_routes_main_and_subagent_paths(manager):
    m, sessions, base, key = manager
    await m._handle(
        {
            str(base / key / "abc-123.jsonl"),
            str(base / key / "def-456" / "subagents" / "agent-9.jsonl"),
            str(base / key / "memory" / "MEMORY.md"),  # not a transcript
            str(base / "unrelated-key" / "zzz.jsonl"),  # not an onboarded project
        }
    )
    assert sorted(sessions.calls) == [("abc-123", "prj_w"), ("def-456", "prj_w")]


async def test_handle_respects_suppression(manager):
    m, sessions, base, key = manager
    m.suppress("abc-123")
    await m._handle({str(base / key / "abc-123.jsonl")})
    assert sessions.calls == []
    m.unsuppress("abc-123")
    await m._handle({str(base / key / "abc-123.jsonl")})
    assert sessions.calls == [("abc-123", "prj_w")]


async def test_project_removed_stops_routing(manager):
    m, sessions, base, key = manager
    await m.project_removed("prj_w")
    await m._handle({str(base / key / "abc-123.jsonl")})
    assert sessions.calls == []


async def test_live_watch_fires_on_new_transcript(manager):
    m, sessions, base, key = manager
    base.mkdir(parents=True, exist_ok=True)
    await m.start([])
    await asyncio.sleep(0.3)  # let awatch attach
    target = base / key
    target.mkdir(parents=True, exist_ok=True)
    (target / "live-1.jsonl").write_text('{"type":"user"}\n')
    deadline = asyncio.get_event_loop().time() + 5
    while not sessions.calls and asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(0.1)
    assert ("live-1", "prj_w") in sessions.calls
