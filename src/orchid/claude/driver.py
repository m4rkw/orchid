import asyncio
import logging
from typing import Any, Callable

from claude_agent_sdk import ResultMessage, SystemMessage

from ..bus import EventBus
from .runner import Runner, RunnerClient, RunnerSpec
from .transcript import TranscriptCache, normalize_stream_message

log = logging.getLogger(__name__)

# A spec factory receives the session id to resume (None = fresh session)
SpecFactory = Callable[[str | None], RunnerSpec]


class SessionDriver:
    """Owns one Claude Code session's client lifecycle.

    All SDK client calls happen inside this driver's single task (anyio task
    affinity); the rest of the app communicates via the command queue (the one
    exception is interrupt(), which the SDK supports cross-task).

    hold_open=True keeps the client alive between turns (onboarding chat).
    Otherwise the client lives for one burst — a turn plus any prompts queued
    behind it — then closes, releasing the session file for terminal use.
    """

    def __init__(
        self,
        runner: Runner,
        spec_factory: SpecFactory,
        bus: EventBus,
        topic: str | None = None,
        hold_open: bool = False,
        *,
        session_id: str | None = None,
        cache: TranscriptCache | None = None,
        status_cb: Callable[["SessionDriver"], None] | None = None,
        on_burst_start: Callable[[str], None] | None = None,
        on_burst_end: Callable[[str], None] | None = None,
    ):
        self._runner = runner
        self._spec_factory = spec_factory
        self._bus = bus
        self._topic = topic  # None -> session:<sid> once the sid is known
        self._hold_open = hold_open
        self._cache = cache
        self._status_cb = status_cb
        self._on_burst_start = on_burst_start
        self._on_burst_end = on_burst_end
        self._queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._client: RunnerClient | None = None
        self._pending_events: list[tuple[str, dict]] = []
        self._sid_event = asyncio.Event()
        self._in_burst = False
        self.queue_len = 0  # prompts enqueued but not yet started
        self.session_id = session_id
        self.state = "idle"
        if session_id:
            self._sid_event.set()

    # -- public surface -----------------------------------------------------

    async def prompt(self, text: str) -> None:
        await self._queue.put(("prompt", text))
        self.queue_len += 1
        self._notify_status()
        self._ensure_task()

    async def reset(self) -> None:
        await self._queue.put(("reset", None))
        self._ensure_task()

    async def interrupt(self) -> bool:
        """Stop the in-flight turn and clear queued prompts. Cross-task safe."""
        if self._client is None or self.state != "running":
            return False
        cleared = 0
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
                cleared += 1
            except asyncio.QueueEmpty:
                break
        self.queue_len = max(0, self.queue_len - cleared)
        self._notify_status()
        try:
            await self._client.interrupt()
        except Exception:
            log.warning("interrupt failed (%s)", self.session_id, exc_info=True)
            return False
        return True

    async def wait_session_id(self, timeout: float = 30.0) -> str:
        await asyncio.wait_for(self._sid_event.wait(), timeout)
        assert self.session_id is not None
        return self.session_id

    async def aclose(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self._close_client()

    # -- internals ----------------------------------------------------------

    def _ensure_task(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name=f"driver:{self._topic or 'new'}")

    def topic(self) -> str | None:
        if self._topic:
            return self._topic
        return f"session:{self.session_id}" if self.session_id else None

    def _publish(self, type_: str, payload: dict) -> None:
        topic = self.topic()
        if topic is None:  # new session, sid not yet known
            self._pending_events.append((type_, payload))
            return
        for t, p in self._pending_events:
            self._bus.publish(topic, t, p)
        self._pending_events.clear()
        self._bus.publish(topic, type_, payload)

    def _notify_status(self) -> None:
        if self._status_cb:
            try:
                self._status_cb(self)
            except Exception:
                log.warning("status callback failed", exc_info=True)

    def _set_session_id(self, sid: str) -> None:
        self.session_id = sid
        self._sid_event.set()
        if self._pending_events:
            topic = self.topic()
            if topic:
                for t, p in self._pending_events:
                    self._bus.publish(topic, t, p)
                self._pending_events.clear()
        self._begin_burst()

    def _begin_burst(self) -> None:
        if not self._in_burst and self._client is not None and self.session_id and not self._hold_open:
            self._in_burst = True
            if self._on_burst_start:
                self._on_burst_start(self.session_id)

    async def _close_client(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            try:
                await self._runner.close(client)
            except Exception:
                log.warning("error closing claude client", exc_info=True)
        if self._in_burst and self.session_id:
            self._in_burst = False
            if self._on_burst_end:
                self._on_burst_end(self.session_id)

    async def _run(self) -> None:
        try:
            while True:
                kind, payload = await self._queue.get()
                if kind == "prompt":
                    self.queue_len = max(0, self.queue_len - 1)
                    await self._do_prompt(payload)
                elif kind == "reset":
                    await self._close_client()
                    self.session_id = None
                    self._sid_event.clear()
                if not self._hold_open and self._queue.empty():
                    await self._close_client()
                    self._notify_status()
        except asyncio.CancelledError:
            raise

    async def _do_prompt(self, text: str) -> None:
        self.state = "running"
        self._notify_status()
        self._publish("turn_started", {})
        try:
            if self._client is None:
                self._client = await self._runner.open(self._spec_factory(self.session_id))
                self._begin_burst()
            await self._client.query(text)
            async for msg in self._client.receive_response():
                if isinstance(msg, SystemMessage):
                    if msg.subtype == "init" and msg.data.get("session_id"):
                        self._set_session_id(msg.data["session_id"])
                    continue
                if isinstance(msg, ResultMessage):
                    self._set_session_id(msg.session_id)
                    self._publish(
                        "turn_completed",
                        {
                            "total_cost_usd": msg.total_cost_usd,
                            "duration_ms": msg.duration_ms,
                            "num_turns": msg.num_turns,
                            "is_error": msg.is_error,
                        },
                    )
                    continue
                normalized = normalize_stream_message(msg)
                if normalized is None:
                    continue
                if self._cache is not None and self.session_id:
                    if not self._cache.append_live(self.session_id, normalized):
                        continue  # already known (e.g. watcher ingested it)
                self._publish("message", {"message": normalized.model_dump()})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("driver turn failed (%s)", self.topic())
            self._publish("error", {"message": f"{type(exc).__name__}: {exc}"})
            # drop the client; the next prompt reopens with resume=session_id
            await self._close_client()
        finally:
            self.state = "idle"
            self._notify_status()
