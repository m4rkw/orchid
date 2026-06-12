import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    bus = ws.app.state.bus
    await ws.accept()
    sub = bus.subscribe()

    async def sender() -> None:
        while True:
            envelope = await sub.queue.get()
            await ws.send_json(envelope)

    async def receiver() -> None:
        while True:
            try:
                data = await ws.receive_json()
            except WebSocketDisconnect:
                return
            kind, topic = data.get("type"), data.get("topic")
            if not isinstance(topic, str) or topic == "sidebar":
                continue
            if kind == "subscribe":
                sub.topics.add(topic)
            elif kind == "unsubscribe":
                sub.topics.discard(topic)

    async def reaper() -> None:
        await sub.dead.wait()  # slow consumer: force a reconnect cycle

    tasks = [asyncio.create_task(c()) for c in (sender, receiver, reaper)]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for t in tasks:
            t.cancel()
        bus.unsubscribe(sub)
