import asyncio
from dataclasses import dataclass, field
from typing import Any


@dataclass(eq=False)
class Subscriber:
    queue: asyncio.Queue
    topics: set[str]
    dead: asyncio.Event = field(default_factory=asyncio.Event)


class EventBus:
    """In-process pub/sub with per-topic monotonic sequence numbers.

    Subscribers that fall behind (bounded queue overflow) are marked dead and
    must reconnect; transcripts are recoverable over REST via the seq watermark.
    """

    def __init__(self, max_queue: int = 1000):
        self._max_queue = max_queue
        self._subs: set[Subscriber] = set()
        self._seq: dict[str, int] = {}

    def subscribe(self, topics: set[str] | None = None) -> Subscriber:
        sub = Subscriber(
            queue=asyncio.Queue(maxsize=self._max_queue),
            topics={"sidebar"} | (topics or set()),
        )
        self._subs.add(sub)
        return sub

    def unsubscribe(self, sub: Subscriber) -> None:
        self._subs.discard(sub)

    def current_seq(self, topic: str) -> int:
        return self._seq.get(topic, 0)

    def publish(self, topic: str, type_: str, payload: dict[str, Any]) -> dict[str, Any]:
        seq = self._seq.get(topic, 0) + 1
        self._seq[topic] = seq
        envelope = {"topic": topic, "seq": seq, "type": type_, "payload": payload}
        for sub in list(self._subs):
            if topic not in sub.topics:
                continue
            try:
                sub.queue.put_nowait(envelope)
            except asyncio.QueueFull:
                sub.dead.set()
        return envelope
