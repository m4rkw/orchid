import threading
import time
from types import SimpleNamespace
from typing import Any

import pytest
import uvicorn

from orchid.config import Settings


@pytest.fixture
def homes(tmp_path, monkeypatch):
    """Isolate ORCHID_HOME and CLAUDE_CONFIG_DIR so tests never touch real state."""
    orchid_home = tmp_path / "orchid_home"
    claude_config = tmp_path / "claude_config"
    orchid_home.mkdir()
    claude_config.mkdir()
    monkeypatch.setenv("ORCHID_HOME", str(orchid_home))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude_config))
    return SimpleNamespace(orchid_home=orchid_home, claude_config=claude_config, tmp=tmp_path)


@pytest.fixture
def settings(homes) -> Settings:
    return Settings.from_env()


class FakeClient:
    """Scripted RunnerClient: each turn is a list of SDK messages, an Exception
    to raise, or an asyncio.Event gate (stream blocks until set; interrupt sets it)."""

    def __init__(self, turns: list[list[Any]]):
        self.turns = list(turns)
        self.queries: list[str] = []
        self.interrupted = False
        self.closed = False
        self._gates: list = []

    async def query(self, prompt: str, session_id: str = "default") -> None:
        self.queries.append(prompt)

    async def receive_response(self):
        import asyncio

        for item in self.turns.pop(0):
            if isinstance(item, Exception):
                raise item
            if isinstance(item, asyncio.Event):
                self._gates.append(item)
                await item.wait()
                continue
            yield item

    async def interrupt(self) -> None:
        self.interrupted = True
        for gate in self._gates:
            gate.set()


class FakeRunner:
    """Yields one FakeClient per open(); records specs for assertions."""

    def __init__(self, scripts: list[list[list[Any]]] | None = None):
        self.scripts = list(scripts or [])
        self.opened: list[tuple[Any, FakeClient]] = []
        self.closed: list[FakeClient] = []

    async def open(self, spec) -> FakeClient:
        client = FakeClient(self.scripts.pop(0) if self.scripts else [])
        self.opened.append((spec, client))
        return client

    async def close(self, client: FakeClient) -> None:
        client.closed = True
        self.closed.append(client)


@pytest.fixture
def fake_runner():
    return FakeRunner


@pytest.fixture
def server_app(homes):
    """Live uvicorn server on an ephemeral port; REST exercised with requests."""
    from orchid.api.app import create_app

    app = create_app(Settings.from_env(), runner=FakeRunner())
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    srv = uvicorn.Server(config)
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not srv.started:
        if time.time() > deadline:
            raise RuntimeError("test server failed to start")
        time.sleep(0.01)
    port = srv.servers[0].sockets[0].getsockname()[1]
    yield SimpleNamespace(url=f"http://127.0.0.1:{port}", app=app)
    srv.should_exit = True
    thread.join(timeout=5)


@pytest.fixture
def server(server_app) -> str:
    return server_app.url
