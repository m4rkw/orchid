import asyncio
from pathlib import Path

import pytest

from orchid.bus import EventBus
from orchid.store import collaboration_store as cs
from orchid.claude.collaboration import CollaborationManager

pytestmark = pytest.mark.asyncio


# -- store tests --------------------------------------------------------------


def test_store_roundtrip(tmp_path):
    home = tmp_path / "orchid_home"
    home.mkdir()
    collab = cs.make_collab("test collab", [
        {"project_id": "p1", "label": "Alpha", "session_id": None},
        {"project_id": "p2", "label": "Beta", "session_id": None},
    ])
    cs.write_collab(home, collab)
    loaded = cs.read_collab(home, collab["id"])
    assert loaded is not None
    assert loaded["title"] == "test collab"
    assert len(loaded["participants"]) == 2
    assert loaded["state"] == "active"


def test_add_message(tmp_path):
    home = tmp_path / "orchid_home"
    home.mkdir()
    collab = cs.make_collab("test", [
        {"project_id": "p1", "label": "A", "session_id": None},
    ])
    msg = cs.add_message(collab, "user", "You", "hello")
    assert msg["sender"] == "user"
    assert msg["content"] == "hello"
    assert len(collab["messages"]) == 1
    cs.write_collab(home, collab)
    loaded = cs.read_collab(home, collab["id"])
    assert len(loaded["messages"]) == 1


def test_list_and_delete(tmp_path):
    home = tmp_path / "orchid_home"
    home.mkdir()
    c1 = cs.make_collab("first", [])
    c2 = cs.make_collab("second", [])
    cs.write_collab(home, c1)
    cs.write_collab(home, c2)
    assert len(cs.list_collabs(home)) == 2
    cs.delete_collab(home, c1["id"])
    assert len(cs.list_collabs(home)) == 1
    assert cs.read_collab(home, c1["id"]) is None


def test_invalid_id_rejected():
    assert cs._collab_file(Path("/tmp"), "bad-id") is None
    assert cs._collab_file(Path("/tmp"), "col_abcdef123456") is not None


# -- manager tests (with fakes) -----------------------------------------------


class FakeRegistry:
    def __init__(self, entries):
        self._entries = entries

    def find(self, pid):
        return next((e for e in self._entries if e["id"] == pid), None)

    def list(self):
        return list(self._entries)


class FakeDriverManager:
    def __init__(self):
        self._projects_of = {}
        self._drivers = {}
        self.prompted = []

    def is_running(self, sid):
        return False

    def active_sessions_for_project(self, pid):
        return []

    async def prompt(self, sid, text, force=False):
        self.prompted.append((sid, text, force))


async def test_create_collaboration(tmp_path):
    home = tmp_path / "orchid_home"
    home.mkdir()

    root1 = tmp_path / "proj1"
    root1.mkdir()
    (root1 / ".orchid").mkdir()
    (root1 / ".orchid" / "project.json").write_text('{"id":"p1","name":"Alpha"}')

    root2 = tmp_path / "proj2"
    root2.mkdir()
    (root2 / ".orchid").mkdir()
    (root2 / ".orchid" / "project.json").write_text('{"id":"p2","name":"Beta"}')

    from orchid.config import Settings
    settings = Settings(orchid_home=home, claude_config_dir=tmp_path / "claude")

    bus = EventBus()
    registry = FakeRegistry([
        {"id": "p1", "root": str(root1)},
        {"id": "p2", "root": str(root2)},
    ])
    dm = FakeDriverManager()

    mgr = CollaborationManager(dm, registry, bus, settings)
    collab = await mgr.create(["p1", "p2"])

    assert collab["title"] == "Alpha + Beta"
    assert len(collab["participants"]) == 2
    assert collab["messages"] == []
    assert collab["state"] == "active"

    # Verify it was persisted
    loaded = cs.read_collab(home, collab["id"])
    assert loaded is not None
    assert loaded["title"] == "Alpha + Beta"

    # Verify listing
    listing = mgr.list_all()
    assert len(listing) == 1
    assert listing[0]["id"] == collab["id"]

    await mgr.aclose()


async def test_end_collaboration(tmp_path):
    home = tmp_path / "orchid_home"
    home.mkdir()

    root1 = tmp_path / "proj1"
    root1.mkdir()
    (root1 / ".orchid").mkdir()
    (root1 / ".orchid" / "project.json").write_text('{"id":"p1","name":"A"}')

    root2 = tmp_path / "proj2"
    root2.mkdir()
    (root2 / ".orchid").mkdir()
    (root2 / ".orchid" / "project.json").write_text('{"id":"p2","name":"B"}')

    from orchid.config import Settings
    settings = Settings(orchid_home=home, claude_config_dir=tmp_path / "claude")

    bus = EventBus()
    registry = FakeRegistry([
        {"id": "p1", "root": str(root1)},
        {"id": "p2", "root": str(root2)},
    ])
    dm = FakeDriverManager()

    mgr = CollaborationManager(dm, registry, bus, settings)
    collab = await mgr.create(["p1", "p2"])
    ended = await mgr.end(collab["id"])
    assert ended["state"] == "completed"

    loaded = cs.read_collab(home, collab["id"])
    assert loaded["state"] == "completed"

    await mgr.aclose()


async def test_send_user_message(tmp_path):
    home = tmp_path / "orchid_home"
    home.mkdir()

    root1 = tmp_path / "proj1"
    root1.mkdir()
    (root1 / ".orchid").mkdir()
    (root1 / ".orchid" / "project.json").write_text('{"id":"p1","name":"A"}')

    root2 = tmp_path / "proj2"
    root2.mkdir()
    (root2 / ".orchid").mkdir()
    (root2 / ".orchid" / "project.json").write_text('{"id":"p2","name":"B"}')

    from orchid.config import Settings
    settings = Settings(orchid_home=home, claude_config_dir=tmp_path / "claude")

    bus = EventBus()
    registry = FakeRegistry([
        {"id": "p1", "root": str(root1)},
        {"id": "p2", "root": str(root2)},
    ])
    dm = FakeDriverManager()

    mgr = CollaborationManager(dm, registry, bus, settings)
    collab = await mgr.create(["p1", "p2"])

    msg = await mgr.send_message(collab["id"], "hello agents")
    assert msg["content"] == "hello agents"
    assert msg["sender"] == "user"

    # Wait a tick to let relay task start/fail (no active sessions)
    await asyncio.sleep(0.2)

    loaded = cs.read_collab(home, collab["id"])
    assert len(loaded["messages"]) >= 1

    await mgr.aclose()
