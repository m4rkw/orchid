"""Opt-in real-SDK smoke test. Run with: ORCHID_LIVE_TESTS=1 uv run pytest tests/test_live_sdk.py

Proves the contract Orchid most depends on: an Orchid-driven session is a real
Claude Code session, resumable from a terminal by the same id, with its
transcript on disk under the Claude config dir.
"""
import os
from pathlib import Path

import pytest

from orchid.bus import EventBus
from orchid.claude.catalog import Catalog
from orchid.claude.driver_manager import DriverManager
from orchid.claude.runner import SdkRunner
from orchid.claude.transcript import TranscriptCache
from orchid.config import Settings
from orchid.services import SessionService
from orchid.store import project_store
from orchid.store.registry import Registry
from orchid.watch.watcher import WatcherManager

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.environ.get("ORCHID_LIVE_TESTS") != "1",
        reason="set ORCHID_LIVE_TESTS=1 to run real Claude SDK calls",
    ),
]


async def test_orchid_session_is_real_and_on_disk(tmp_path):
    # Real CLI config dir (resume must find the transcript), isolated orchid home.
    settings = Settings(
        orchid_home=tmp_path / "orchid",
        claude_config_dir=Path("~/.claude").expanduser(),
    )
    settings.orchid_home.mkdir(parents=True)
    workspace = tmp_path / "ws"
    workspace.mkdir()

    registry = Registry(settings.registry_path)
    project_store.init_project(workspace, "prj_live", "Live")
    entry = registry.add("prj_live", workspace)
    bus, cache, catalog = EventBus(), TranscriptCache(), Catalog()
    sessions = SessionService(registry, catalog, cache, bus, settings)
    watcher = WatcherManager(catalog, sessions, settings)
    manager = DriverManager(SdkRunner(), bus, cache, sessions, watcher, settings)
    sessions.is_running = manager.is_running
    sessions.live_agents = manager.live_agents

    try:
        sid = await manager.create_session(
            entry, "Reply with exactly the word: pong. Do not use any tools.",
            model="haiku",
        )
        assert sid
        # transcript exists on disk under the real config dir
        key = (await catalog.project_keys(workspace))[0]
        transcript = settings.claude_config_dir / "projects" / key / f"{sid}.jsonl"
        # poll briefly; the CLI flushes on turn end
        for _ in range(50):
            if transcript.exists():
                break
            await __import__("asyncio").sleep(0.2)
        assert transcript.exists(), f"no transcript at {transcript}"

        # the catalog (resume path) can see it by id
        info = await catalog.session_info(sid, workspace)
        assert info is not None and info.session_id == sid
    finally:
        await manager.aclose()
