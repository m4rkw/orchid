"""Collaboration session manager: mediated multi-agent conversations.

A collaboration is a turn-based conversation between agents from different
projects, with the user able to observe and interject.  Each agent is backed by
a real Claude Code session (existing or freshly prompted); the manager relays
formatted context between them and publishes events so the frontend can show a
unified chat timeline.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, TYPE_CHECKING

from ..bus import EventBus
from ..store import collaboration_store as cs, project_store

if TYPE_CHECKING:
    from .driver_manager import DriverManager
    from ..services import ProjectService
    from ..store.registry import Registry
    from ..config import Settings

log = logging.getLogger(__name__)

MAX_RESPONSE_CHARS = 100_000
MAX_CONTEXT_MESSAGES = 20


class CollaborationManager:

    def __init__(
        self,
        dm: DriverManager,
        registry: Registry,
        bus: EventBus,
        settings: Settings,
        project_service: ProjectService | None = None,
    ):
        self._dm = dm
        self._registry = registry
        self._bus = bus
        self._settings = settings
        self._project_service = project_service
        self._tasks: dict[str, asyncio.Task] = {}

    # -- public API -----------------------------------------------------------

    async def create(self, project_ids: list[str]) -> dict[str, Any]:
        participants = []
        labels = []
        for pid in project_ids:
            entry = self._registry.find(pid)
            if entry is None:
                raise ValueError(f"unknown project: {pid}")
            pf = project_store.read_project_file(Path(entry["root"])) or {}
            label = pf.get("name", Path(entry["root"]).name)
            labels.append(label)
            participants.append({
                "project_id": pid,
                "label": label,
                "session_id": None,
            })

        title = " + ".join(labels)
        collab = cs.make_collab(title, participants)
        cs.write_collab(self._settings.orchid_home, collab)

        self._publish(collab["id"], "collab_created", {
            "collaboration": self._summary(collab),
        })
        self._bus.publish("sidebar", "collab_updated", {
            "collaboration": self._summary(collab),
        })
        return collab

    async def send_message(self, collab_id: str, text: str) -> dict[str, Any]:
        collab = self._load(collab_id)
        if collab["state"] != "active":
            raise ValueError("collaboration is not active")

        self._cancel_task(collab_id)

        msg = cs.add_message(collab, "user", "You", text)
        cs.write_collab(self._settings.orchid_home, collab)
        self._publish(collab_id, "collab_message", {"message": msg})

        if collab.get("auto_continue", True):
            self._start_relay(collab_id, target_index=0)
        return msg

    async def continue_relay(self, collab_id: str, target_index: int | None = None) -> None:
        collab = self._load(collab_id)
        if collab["state"] != "active":
            raise ValueError("collaboration is not active")
        idx = target_index if target_index is not None else self._next_agent_index(collab)
        self._start_relay(collab_id, target_index=idx)

    async def set_auto_continue(self, collab_id: str, value: bool) -> None:
        collab = self._load(collab_id)
        collab["auto_continue"] = value
        cs.write_collab(self._settings.orchid_home, collab)

    async def end(self, collab_id: str) -> dict[str, Any]:
        collab = self._load(collab_id)
        self._cancel_task(collab_id)
        collab["state"] = "completed"
        cs.write_collab(self._settings.orchid_home, collab)
        self._publish(collab_id, "collab_ended", {})
        self._bus.publish("sidebar", "collab_updated", {
            "collaboration": self._summary(collab),
        })
        return collab

    def get(self, collab_id: str) -> dict[str, Any]:
        return self._load(collab_id)

    def list_all(self) -> list[dict[str, Any]]:
        return [
            self._summary(c)
            for c in cs.list_collabs(self._settings.orchid_home)
        ]

    async def delete(self, collab_id: str) -> None:
        self._cancel_task(collab_id)
        cs.delete_collab(self._settings.orchid_home, collab_id)
        self._publish(collab_id, "collab_ended", {})
        self._bus.publish("sidebar", "collab_removed", {"collab_id": collab_id})

    # -- relay logic ----------------------------------------------------------

    def _start_relay(self, collab_id: str, target_index: int) -> None:
        self._cancel_task(collab_id)
        task = asyncio.create_task(
            self._relay_loop(collab_id, target_index),
            name=f"collab:{collab_id}",
        )
        self._tasks[collab_id] = task
        task.add_done_callback(lambda _: self._tasks.pop(collab_id, None))

    def _cancel_task(self, collab_id: str) -> None:
        task = self._tasks.pop(collab_id, None)
        if task and not task.done():
            task.cancel()

    async def _relay_loop(self, collab_id: str, start_index: int) -> None:
        """Prompt each participant once (one full cycle), then pause."""
        idx = start_index
        active_turn: dict | None = None
        try:
            collab = self._load(collab_id)
            n_participants = len(collab.get("participants", []))
            if not n_participants:
                return

            for turn in range(n_participants):
                collab = self._load(collab_id)
                if collab["state"] != "active":
                    break
                participants = collab["participants"]

                p = participants[idx % n_participants]
                pid = p["project_id"]
                label = p["label"]
                active_turn = {
                    "participant_index": idx % n_participants,
                    "project_id": pid,
                    "label": label,
                }

                self._publish(collab_id, "collab_turn_started", active_turn)

                context = self._format_context(collab, pid)
                response, ok = await self._prompt_agent(collab, idx % n_participants, context)

                collab = self._load(collab_id)
                if collab["state"] != "active":
                    break

                msg = cs.add_message(collab, pid, label, response)
                cs.write_collab(self._settings.orchid_home, collab)
                self._publish(collab_id, "collab_message", {"message": msg})
                self._publish(collab_id, "collab_turn_completed", {
                    "participant_index": idx % n_participants,
                    "project_id": pid,
                })
                active_turn = None
                self._bus.publish("sidebar", "collab_updated", {
                    "collaboration": self._summary(collab),
                })

                if not ok:
                    break

                idx += 1
                if turn < n_participants - 1:
                    await asyncio.sleep(0.5)

        except asyncio.CancelledError:
            pass
        except Exception:
            log.exception("collaboration relay failed for %s", collab_id)
            self._publish(collab_id, "collab_error", {
                "message": "relay failed — check orchid logs",
            })
        finally:
            if active_turn:
                self._publish(collab_id, "collab_turn_completed", {
                    "participant_index": active_turn["participant_index"],
                    "project_id": active_turn["project_id"],
                })

    async def _prompt_agent(
        self, collab: dict, participant_index: int, context: str,
    ) -> tuple[str, bool]:
        """Returns (response_text, success).  On failure the text is an error
        message and success=False so the relay loop stops."""
        p = collab["participants"][participant_index]
        pid = p["project_id"]
        label = p["label"]

        sid = await self._find_session(pid)
        if sid is None:
            return f"[No session for {label} — create one in the project first]", False

        if self._dm.is_running(sid):
            return (
                f"[{label}'s session is busy with another task. "
                "Wait for it to finish or start a new session in that project.]"
            ), False

        p["session_id"] = sid
        cs.write_collab(self._settings.orchid_home, collab)

        sub = self._bus.subscribe({f"session:{sid}"})
        try:
            await self._dm.prompt(sid, context, force=True)
        except Exception as exc:
            self._bus.unsubscribe(sub)
            return f"[Failed to reach {label}: {exc}]", False

        text = await self._collect_response(sub, sid, timeout_s=1800)
        return text, True

    async def _collect_response(
        self, sub: Any, sid: str, timeout_s: float,
    ) -> str:
        texts: list[str] = []
        total = 0
        saw_start = False
        try:
            deadline = asyncio.get_event_loop().time() + timeout_s
            while True:
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    raise asyncio.TimeoutError()
                if sub.dead.is_set():
                    texts.append("\n\n[Bus overflow — response lost]")
                    break
                envelope = await asyncio.wait_for(sub.queue.get(), timeout=remaining)
                etype = envelope["type"]
                if etype == "turn_started":
                    saw_start = True
                    texts.clear()
                    total = 0
                elif etype == "message" and saw_start:
                    msg = envelope["payload"].get("message", {})
                    if msg.get("role") == "assistant":
                        for block in msg.get("blocks", []):
                            if block.get("type") == "text" and block.get("text"):
                                t = block["text"]
                                room = MAX_RESPONSE_CHARS - total
                                if room <= 0:
                                    continue
                                if len(t) > room:
                                    t = t[:room]
                                    texts.append(t)
                                    texts.append("\n[truncated]")
                                    total = MAX_RESPONSE_CHARS
                                else:
                                    texts.append(t)
                                    total += len(t)
                elif etype == "turn_completed" and saw_start:
                    break
                elif etype == "error" and saw_start:
                    err = envelope["payload"].get("message", "unknown")
                    texts.append(f"\n[Error: {err}]")
                    break
        except asyncio.TimeoutError:
            texts.append(f"\n[Timed out after {timeout_s}s]")
        finally:
            self._bus.unsubscribe(sub)
        return "\n\n".join(texts) if texts else "(no response)"

    async def _find_session(self, project_id: str) -> str | None:
        """Find the best session for a project: prefer idle driver, then any
        Orchid-owned session from the catalog (the prompt call will build a
        driver for it).  Retries briefly if all sessions are busy (e.g. the
        previous relay turn just finished and the driver is still closing)."""
        for attempt in range(6):
            if attempt > 0:
                await asyncio.sleep(1.0)
            # 1. Already has a driver and is idle
            for sid, pid in self._dm._projects_of.items():
                if pid == project_id and sid in self._dm._drivers:
                    if not self._dm.is_running(sid):
                        return sid
            # 2. Any Orchid-owned session via ProjectService
            if self._project_service:
                try:
                    summaries = await self._project_service.sessions(project_id)
                    idle = [s for s in summaries if not self._dm.is_running(s.id)]
                    if idle:
                        return idle[0].id
                    if summaries and not idle:
                        log.warning("_find_session %s: %d sessions all busy (attempt %d)",
                                    project_id, len(summaries), attempt + 1)
                        continue
                except Exception:
                    log.warning("_find_session catalog lookup failed for %s",
                                project_id, exc_info=True)
            else:
                log.warning("_find_session: no project_service available")
                break
        return None

    def _format_context(self, collab: dict, target_pid: str) -> str:
        parts = [f"[Collaboration: \"{collab['title']}\"]", ""]

        recent = collab["messages"][-MAX_CONTEXT_MESSAGES:]
        if recent:
            for m in recent:
                sender = m["sender_label"]
                if m["sender"] == "user":
                    parts.append(f"[You (the human user)]: {m['content']}")
                elif m["sender"] == target_pid:
                    parts.append(f"[You said earlier]: {m['content']}")
                else:
                    parts.append(f"[{sender}]: {m['content']}")
            parts.append("")

        other_labels = [
            p["label"] for p in collab["participants"]
            if p["project_id"] != target_pid
        ]
        others = ", ".join(other_labels) if other_labels else "other agents"
        parts.append(
            f"You are collaborating with {others}. "
            "Respond to the latest message. Be direct and actionable."
        )
        return "\n".join(parts)

    def _next_agent_index(self, collab: dict) -> int:
        messages = collab["messages"]
        participants = collab["participants"]
        if not participants:
            return 0
        for m in reversed(messages):
            if m["sender"] == "user":
                return 0
            for i, p in enumerate(participants):
                if p["project_id"] == m["sender"]:
                    return (i + 1) % len(participants)
        return 0

    # -- helpers --------------------------------------------------------------

    def _load(self, collab_id: str) -> dict[str, Any]:
        collab = cs.read_collab(self._settings.orchid_home, collab_id)
        if collab is None:
            raise ValueError(f"collaboration not found: {collab_id}")
        return collab

    def _publish(self, collab_id: str, type_: str, payload: dict) -> None:
        self._bus.publish(f"collab:{collab_id}", type_, payload)

    def _summary(self, collab: dict) -> dict[str, Any]:
        return {
            "id": collab["id"],
            "title": collab["title"],
            "participants": [
                {"project_id": p["project_id"], "label": p["label"]}
                for p in collab["participants"]
            ],
            "message_count": len(collab["messages"]),
            "state": collab["state"],
            "auto_continue": collab.get("auto_continue", True),
            "created_at": collab["created_at"],
            "updated_at": collab["updated_at"],
        }

    async def aclose(self) -> None:
        for cid in list(self._tasks):
            self._cancel_task(cid)
