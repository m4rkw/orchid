"""Out-of-band notifications when Orchid needs the human.

Browser desktop notifications are handled client-side off the existing WS
events; this module is the optional server-side Pushover channel, so a session
blocked on approval (which auto-denies after 300s) reaches you when no tab is
open. Disabled unless both ORCHID_PUSHOVER_TOKEN and ORCHID_PUSHOVER_USER are set.
"""

import asyncio
import logging

import requests

from .config import Settings

log = logging.getLogger(__name__)

_PUSHOVER_URL = "https://api.pushover.net/1/messages.json"


class Notifier:
    def __init__(self, settings: Settings):
        self._token = settings.pushover_token
        self._user = settings.pushover_user
        self._base = settings.public_base_url
        # Keep strong refs to in-flight fire-and-forget tasks: the event loop
        # only holds weak refs, so an unreferenced task can be GC'd mid-send.
        self._tasks: set = set()

    @property
    def pushover_enabled(self) -> bool:
        return bool(self._token and self._user)

    def session_url(self, project_id: str | None, session_id: str | None) -> str:
        if project_id and session_id:
            return f"{self._base}/?project={project_id}&session={session_id}"
        return self._base

    def review_url(self, project_id: str | None, review_id: str | None) -> str:
        if project_id and review_id:
            return f"{self._base}/?project={project_id}&review={review_id}"
        return self._base

    def push_bg(self, title: str, message: str, url: str | None = None,
                url_title: str | None = None) -> None:
        """Fire-and-forget from a sync call site (a tool handler / the broker),
        holding a strong ref so the task can't be garbage-collected mid-send."""
        if not self.pushover_enabled:
            return
        import asyncio as _asyncio
        task = _asyncio.create_task(self.push(title, message, url, url_title))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def push(self, title: str, message: str, url: str | None = None,
                   url_title: str | None = None) -> None:
        """Best-effort Pushover send. Never raises; runs the blocking HTTP call
        off the event loop so it can't stall the owning session task."""
        if not self.pushover_enabled:
            return
        try:
            await asyncio.to_thread(self._send, title, message, url, url_title)
        except Exception:
            log.warning("pushover notification failed", exc_info=True)

    def _send(self, title: str, message: str, url: str | None, url_title: str | None) -> None:
        data = {"token": self._token, "user": self._user, "title": title, "message": message}
        if url:
            data["url"] = url
            data["url_title"] = url_title or "Open in Orchid"
        requests.post(_PUSHOVER_URL, data=data, timeout=10)
