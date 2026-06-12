import asyncio
import logging
from typing import Any, Callable

from claude_agent_sdk import ResultMessage, SystemMessage

from ..bus import EventBus
from .runner import Runner, RunnerClient, RunnerSpec
from .transcript import normalize_stream_message

log = logging.getLogger(__name__)

# A spec factory receives the session id to resume (None = fresh session)
SpecFactory = Callable[[str | None], RunnerSpec]


class SessionDriver:
    """Owns one Claude Code session's client lifecycle.

    All SDK client calls happen inside this driver's single task (anyio task
    affinity); the rest of the app communicates via the command queue.
    hold_open=True keeps the client alive between turns (onboarding chat);
    otherwise the client closes when the queue drains, releasing the session
    file for terminal use.
    """

    def __init__(
        self,
        runner: Runner,
        spec_factory: SpecFactory,
        bus: EventBus,
        topic: str,
        hold_open: bool = False,
    ):
        self._runner = runner
        self._spec_factory = spec_factory
        self._bus = bus
        self._topic = topic
        self._hold_open = hold_open
        self._queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._client: RunnerClient | None = None
        self.session_id: str | None = None
        self.state = "idle"

    def _ensure_task(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name=f"driver:{self._topic}")

    async def prompt(self, text: str) -> None:
        await self._queue.put(("prompt", text))
        self._ensure_task()

    async def reset(self) -> None:
        await self._queue.put(("reset", None))
        self._ensure_task()

    async def aclose(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self._close_client()

    async def _close_client(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            try:
                await self._runner.close(client)
            except Exception:
                log.warning("error closing claude client", exc_info=True)

    async def _run(self) -> None:
        try:
            while True:
                kind, payload = await self._queue.get()
                if kind == "prompt":
                    await self._do_prompt(payload)
                elif kind == "reset":
                    await self._close_client()
                    self.session_id = None
                if not self._hold_open and self._queue.empty():
                    await self._close_client()
        except asyncio.CancelledError:
            raise

    async def _do_prompt(self, text: str) -> None:
        self.state = "running"
        self._bus.publish(self._topic, "turn_started", {})
        try:
            if self._client is None:
                self._client = await self._runner.open(self._spec_factory(self.session_id))
            await self._client.query(text)
            async for msg in self._client.receive_response():
                if isinstance(msg, SystemMessage):
                    if msg.subtype == "init" and msg.data.get("session_id"):
                        self.session_id = msg.data["session_id"]
                    continue
                if not isinstance(msg, ResultMessage):
                    normalized = normalize_stream_message(msg)
                    if normalized is not None:
                        self._bus.publish(self._topic, "message", {"message": normalized.model_dump()})
                else:  # the UI synthesizes the turn divider from turn_completed
                    self.session_id = msg.session_id
                    self._bus.publish(
                        self._topic,
                        "turn_completed",
                        {
                            "total_cost_usd": msg.total_cost_usd,
                            "duration_ms": msg.duration_ms,
                            "num_turns": msg.num_turns,
                            "is_error": msg.is_error,
                        },
                    )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("driver turn failed (%s)", self._topic)
            self._bus.publish(self._topic, "error", {"message": f"{type(exc).__name__}: {exc}"})
            # drop the client; the next prompt reopens with resume=session_id
            await self._close_client()
        finally:
            self.state = "idle"
