import asyncio
import json

import pytest
import requests
from websockets.asyncio.client import connect

pytestmark = pytest.mark.asyncio


async def test_sidebar_event_on_project_create(server, homes):
    target = homes.tmp / "wsproj"
    target.mkdir()
    ws_url = server.replace("http://", "ws://") + "/ws"

    async with connect(ws_url) as ws:
        await asyncio.to_thread(
            requests.post, f"{server}/api/projects", json={"path": str(target)}, timeout=5
        )
        async with asyncio.timeout(5):
            while True:
                evt = json.loads(await ws.recv())
                if evt["type"] == "project_added":
                    break
    assert evt["topic"] == "sidebar"
    assert evt["seq"] >= 1
    assert evt["payload"]["project"]["root"] == str(target.resolve())


async def test_subscribe_roundtrip_accepted(server):
    ws_url = server.replace("http://", "ws://") + "/ws"
    async with connect(ws_url) as ws:
        await ws.send(json.dumps({"type": "subscribe", "topic": "onboarding"}))
        await ws.send(json.dumps({"type": "unsubscribe", "topic": "onboarding"}))
        # connection stays healthy after control messages
        await asyncio.sleep(0.1)
        await ws.send(json.dumps({"type": "subscribe", "topic": "session:abc"}))
