"""Tests for the inbox: store + API integration + notify/config wiring."""

import asyncio
import dataclasses
import json

import pytest
import requests
from websockets.asyncio.client import connect

from orchid.config import Settings
from orchid.notify import Notifier
from orchid.store import inbox_store


# --------------------------------------------------------------------------- #
# Store unit tests
# --------------------------------------------------------------------------- #

def _item(item_id, *, status="pending", created_at="2026-01-01T00:00:00+00:00", **extra):
    base = {
        "id": item_id,
        "project_id": "prj_x",
        "source": "docmgr",
        "title": f"Item {item_id}",
        "status": status,
        "options": [{"id": "ok", "label": "OK"}],
        "context": {},
        "created_at": created_at,
    }
    base.update(extra)
    return base


def test_store_roundtrip(tmp_path):
    item_id = inbox_store.new_item_id()
    assert item_id.startswith("inb_")
    item = _item(item_id, body="hello", context={"k": "v"})
    inbox_store.write_item(tmp_path, item)

    loaded = inbox_store.read_item(tmp_path, item_id)
    assert loaded is not None
    assert loaded["title"] == f"Item {item_id}"
    assert loaded["body"] == "hello"
    assert loaded["context"] == {"k": "v"}
    assert loaded["status"] == "pending"


def test_store_read_bad_id_returns_none(tmp_path):
    # Malformed id (fails the id regex / path traversal guard).
    assert inbox_store.read_item(tmp_path, "../../etc/passwd") is None
    assert inbox_store.read_item(tmp_path, "not_an_inbox_id") is None


def test_store_read_mismatched_id_returns_none(tmp_path):
    item_id = inbox_store.new_item_id()
    other_id = inbox_store.new_item_id()
    # Persist an item whose stored `id` differs from its filename's id.
    inbox_store.write_item(tmp_path, _item(other_id))
    path = inbox_store.inbox_dir(tmp_path) / f"{item_id}.json"
    path.write_text(json.dumps(_item(other_id)))
    assert inbox_store.read_item(tmp_path, item_id) is None


def test_store_list_ordering_pending_first_then_newest(tmp_path):
    # Pending items float above resolved ones; within a group, newest-first.
    inbox_store.write_item(tmp_path, _item("inb_aaaaaa01", status="resolved",
                                           created_at="2026-01-05T00:00:00+00:00"))
    inbox_store.write_item(tmp_path, _item("inb_aaaaaa02", status="pending",
                                           created_at="2026-01-02T00:00:00+00:00"))
    inbox_store.write_item(tmp_path, _item("inb_aaaaaa03", status="pending",
                                           created_at="2026-01-04T00:00:00+00:00"))
    inbox_store.write_item(tmp_path, _item("inb_aaaaaa04", status="dismissed",
                                           created_at="2026-01-03T00:00:00+00:00"))

    ids = [i["id"] for i in inbox_store.list_items(tmp_path)]
    # Pending newest-first, then the non-pending newest-first.
    assert ids == ["inb_aaaaaa03", "inb_aaaaaa02", "inb_aaaaaa01", "inb_aaaaaa04"]


def test_store_list_empty_when_no_dir(tmp_path):
    assert inbox_store.list_items(tmp_path) == []


def test_store_delete(tmp_path):
    item_id = inbox_store.new_item_id()
    inbox_store.write_item(tmp_path, _item(item_id))
    assert inbox_store.delete_item(tmp_path, item_id) is True
    assert inbox_store.read_item(tmp_path, item_id) is None
    # Deleting again / unknown id → False.
    assert inbox_store.delete_item(tmp_path, item_id) is False
    assert inbox_store.delete_item(tmp_path, "bad_id") is False


# --------------------------------------------------------------------------- #
# API integration tests (live uvicorn + requests)
# --------------------------------------------------------------------------- #

def _register_project(server, homes, name):
    target = homes.tmp / name
    target.mkdir()
    return requests.post(f"{server}/api/projects", json={"path": str(target)}, timeout=5).json()["id"]


def _create_item(server, pid, **body):
    payload = {"source": "docmgr", "title": "Decide", **body}
    r = requests.post(f"{server}/api/projects/{pid}/inbox", json=payload, timeout=5)
    assert r.status_code == 200, r.text
    return r.json()


def test_api_create_appears_in_project_and_global_lists(server, homes):
    pid = _register_project(server, homes, "inbproj")
    item = _create_item(server, pid, options=[{"id": "yes", "label": "Yes"}],
                        context={"doc": 1})
    assert item["id"].startswith("inb_")
    assert item["status"] == "pending"
    assert item["resolution"] is None
    assert item["created_at"]
    assert item["context"] == {"doc": 1}

    per_project = requests.get(f"{server}/api/projects/{pid}/inbox", timeout=5).json()
    assert [i["id"] for i in per_project] == [item["id"]]

    aggregate = requests.get(f"{server}/api/inbox", timeout=5).json()
    assert item["id"] in [i["id"] for i in aggregate]


def test_api_global_aggregate_spans_projects(server, homes):
    pid_a = _register_project(server, homes, "inbA")
    pid_b = _register_project(server, homes, "inbB")
    a = _create_item(server, pid_a, title="from A")
    b = _create_item(server, pid_b, title="from B")
    ids = {i["id"] for i in requests.get(f"{server}/api/inbox", timeout=5).json()}
    assert {a["id"], b["id"]} <= ids


def test_api_status_and_source_filters(server, homes):
    pid = _register_project(server, homes, "inbfilter")
    a = _create_item(server, pid, source="docmgr", title="A")
    b = _create_item(server, pid, source="orchid", title="B")
    # Resolve b so it has a non-pending status.
    requests.post(f"{server}/api/projects/{pid}/inbox/{b['id']}/dismiss", timeout=5)

    pending = requests.get(f"{server}/api/projects/{pid}/inbox?status=pending", timeout=5).json()
    assert [i["id"] for i in pending] == [a["id"]]

    docmgr = requests.get(f"{server}/api/projects/{pid}/inbox?source=docmgr", timeout=5).json()
    assert [i["id"] for i in docmgr] == [a["id"]]

    # Global aggregate honours the same filters.
    g = requests.get(f"{server}/api/inbox?status=dismissed&source=orchid", timeout=5).json()
    assert [i["id"] for i in g] == [b["id"]]


def test_api_resolve_sets_status_and_resolution(server, homes):
    pid = _register_project(server, homes, "inbresolve")
    item = _create_item(server, pid, options=[{"id": "approve", "label": "Approve"}])
    r = requests.post(
        f"{server}/api/projects/{pid}/inbox/{item['id']}/resolve",
        json={"option_id": "approve", "payload": {"note": "lgtm"}}, timeout=5)
    assert r.status_code == 200, r.text
    resolved = r.json()
    assert resolved["status"] == "resolved"
    assert resolved["resolution"]["option_id"] == "approve"
    assert resolved["resolution"]["payload"] == {"note": "lgtm"}

    # A subsequent GET reflects the resolution.
    fetched = requests.get(f"{server}/api/projects/{pid}/inbox/{item['id']}", timeout=5).json()
    assert fetched["status"] == "resolved"
    assert fetched["resolution"]["option_id"] == "approve"


def test_api_resolve_invalid_option_400(server, homes):
    pid = _register_project(server, homes, "inbbadopt")
    item = _create_item(server, pid, options=[{"id": "yes", "label": "Yes"}])
    r = requests.post(
        f"{server}/api/projects/{pid}/inbox/{item['id']}/resolve",
        json={"option_id": "nope"}, timeout=5)
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "INVALID_OPTION"


def test_api_dismiss_sets_status(server, homes):
    pid = _register_project(server, homes, "inbdismiss")
    item = _create_item(server, pid)
    r = requests.post(f"{server}/api/projects/{pid}/inbox/{item['id']}/dismiss", timeout=5)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "dismissed"
    fetched = requests.get(f"{server}/api/projects/{pid}/inbox/{item['id']}", timeout=5).json()
    assert fetched["status"] == "dismissed"


def test_api_unknown_item_404(server, homes):
    pid = _register_project(server, homes, "inb404")
    r = requests.get(f"{server}/api/projects/{pid}/inbox/inb_deadbeef00", timeout=5)
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "INBOX_ITEM_NOT_FOUND"


@pytest.mark.asyncio
async def test_api_create_and_resolve_emit_sidebar_events(server, homes):
    pid = await asyncio.to_thread(_register_project, server, homes, "inbws")
    ws_url = server.replace("http://", "ws://") + "/ws"

    async with connect(ws_url) as ws:
        item = await asyncio.to_thread(_create_item, server, pid,
                                       options=[{"id": "ok", "label": "OK"}])
        async with asyncio.timeout(5):
            while True:
                evt = json.loads(await ws.recv())
                if evt["type"] == "inbox_created":
                    break
        assert evt["topic"] == "sidebar"
        assert evt["payload"]["project_id"] == pid
        assert evt["payload"]["item"]["id"] == item["id"]

        await asyncio.to_thread(
            requests.post,
            f"{server}/api/projects/{pid}/inbox/{item['id']}/resolve",
            json={"option_id": "ok"}, timeout=5)
        async with asyncio.timeout(5):
            while True:
                evt = json.loads(await ws.recv())
                if evt["type"] == "inbox_resolved":
                    break
        assert evt["topic"] == "sidebar"
        assert evt["payload"]["item"]["status"] == "resolved"


# --------------------------------------------------------------------------- #
# notify / config unit tests
# --------------------------------------------------------------------------- #

def test_settings_reads_bare_pushover_env(monkeypatch, homes):
    monkeypatch.delenv("ORCHID_PUSHOVER_TOKEN", raising=False)
    monkeypatch.delenv("ORCHID_PUSHOVER_USER", raising=False)
    monkeypatch.setenv("PUSHOVER_APP_KEY", "app-key")
    monkeypatch.setenv("PUSHOVER_USER_KEY", "user-key")
    s = Settings.from_env()
    assert s.pushover_token == "app-key"
    assert s.pushover_user == "user-key"


def test_settings_orchid_prefixed_env_takes_precedence(monkeypatch, homes):
    monkeypatch.setenv("ORCHID_PUSHOVER_TOKEN", "orchid-tok")
    monkeypatch.setenv("PUSHOVER_APP_KEY", "bare-key")
    monkeypatch.setenv("ORCHID_PUSHOVER_USER", "orchid-usr")
    monkeypatch.setenv("PUSHOVER_USER_KEY", "bare-usr")
    s = Settings.from_env()
    assert s.pushover_token == "orchid-tok"
    assert s.pushover_user == "orchid-usr"


def test_inbox_url_format(settings):
    n = Notifier(dataclasses.replace(settings, base_url="http://lan:9/"))
    assert n.inbox_url("p", "i") == "http://lan:9/?project=p&inbox=i"
    assert n.inbox_url(None, None) == "http://lan:9"  # trailing slash trimmed


def test_first_in_group_suppression(settings):
    n = Notifier(settings)
    assert n.first_in_group("g1") is True   # first time → notify
    assert n.first_in_group("g1") is False  # same group again → suppressed
    assert n.first_in_group("g2") is True   # new group → notify
    # Ungrouped items always notify.
    assert n.first_in_group(None) is True
    assert n.first_in_group(None) is True
    assert n.first_in_group("") is True
