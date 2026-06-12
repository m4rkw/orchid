import json
from datetime import datetime, timezone

import requests
from claude_agent_sdk import SDKSessionInfo, SessionMessage

SID = "99999999-8888-7777-6666-555555555555"


def _stub_catalog(app, root, sid=SID):
    catalog = app.state.catalog
    ts = datetime(2026, 6, 12, 8, 0, tzinfo=timezone.utc)
    info = SDKSessionInfo(
        session_id=sid,
        summary="Stubbed session",
        last_modified=ts,
        file_size=1,
        custom_title=None,
        first_prompt="hi",
        git_branch="main",
        cwd=str(root),
        tag=None,
        created_at=ts,
    )

    async def session_info(s, r):
        return info if s == sid else None

    async def session_messages(s, r):
        return [
            SessionMessage(
                type="assistant",
                uuid="m1",
                session_id=sid,
                message={"role": "assistant", "content": [{"type": "text", "text": "big " * 10000}]},
                parent_tool_use_id=None,
            )
        ]

    async def subagents(s, r):
        return ["agent-x"]

    async def subagent_messages(s, a, r):
        return [
            SessionMessage(
                type="assistant",
                uuid="am1",
                session_id=sid,
                message={"role": "assistant", "content": "agent says hi"},
                parent_tool_use_id=None,
            )
        ]

    state = {"title": None, "deleted": False}

    async def rename(s, title, r):
        state["title"] = title

    async def delete(s, r):
        state["deleted"] = True

    async def fork(s, r, title=None):
        return "forked-sid"

    catalog.session_info = session_info
    catalog.session_messages = session_messages
    catalog.subagents = subagents
    catalog.subagent_messages = subagent_messages
    catalog.rename = rename
    catalog.delete = delete
    catalog.fork = fork
    app.state._stub_state = state


def _make_project(url, homes):
    root = homes.tmp / "sproj"
    root.mkdir(exist_ok=True)
    r = requests.post(f"{url}/api/projects", json={"path": str(root)}, timeout=5)
    assert r.status_code == 201
    return root, r.json()["id"]


def test_session_detail_and_messages(server_app, homes):
    url, app = server_app.url, server_app.app
    root, _pid = _make_project(url, homes)
    _stub_catalog(app, root)

    detail = requests.get(f"{url}/api/sessions/{SID}", timeout=5).json()
    assert detail["title"] == "Stubbed session"
    assert detail["handoff_command"] == f"cd {root} && claude --resume {SID}"

    out = requests.get(f"{url}/api/sessions/{SID}/messages", timeout=5).json()
    assert out["seq"] == 0
    msg = out["messages"][0]
    assert msg["uuid"] == "m1"
    assert msg["blocks"][0]["truncated"] is True
    assert len(msg["blocks"][0]["text"]) == 16384

    full = requests.get(f"{url}/api/sessions/{SID}/messages/m1", timeout=5).json()
    assert full["blocks"][0]["truncated"] is False
    assert len(full["blocks"][0]["text"]) == 40000


def test_session_agents_endpoints(server_app, homes):
    url, app = server_app.url, server_app.app
    root, _pid = _make_project(url, homes)
    _stub_catalog(app, root)

    agents = requests.get(f"{url}/api/sessions/{SID}/agents", timeout=5).json()
    assert agents == [{"agent_id": "agent-x", "message_count": 1, "status": "done"}]

    msgs = requests.get(f"{url}/api/sessions/{SID}/agents/agent-x/messages", timeout=5).json()
    assert msgs["messages"][0]["agent_id"] == "agent-x"
    assert msgs["messages"][0]["blocks"][0]["text"] == "agent says hi"


def test_session_not_found(server_app):
    r = requests.get(f"{server_app.url}/api/sessions/unknown-sid", timeout=5)
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "SESSION_NOT_FOUND"


def test_session_management_endpoints(server_app, homes):
    url, app = server_app.url, server_app.app
    root, _pid = _make_project(url, homes)
    _stub_catalog(app, root)

    assert requests.post(f"{url}/api/sessions/{SID}/rename", json={"title": "Renamed"}, timeout=5).status_code == 200
    assert app.state._stub_state["title"] == "Renamed"

    assert requests.post(f"{url}/api/sessions/{SID}/pin", json={"value": True}, timeout=5).status_code == 200
    assert requests.post(f"{url}/api/sessions/{SID}/archive", json={"value": True}, timeout=5).status_code == 200

    r = requests.post(f"{url}/api/sessions/{SID}/fork", json={}, timeout=5)
    assert r.status_code == 201 and r.json()["session_id"] == "forked-sid"

    # SID mtime is 2026 (old) -> not external -> delete allowed
    assert requests.delete(f"{url}/api/sessions/{SID}", timeout=5).status_code == 204
    assert app.state._stub_state["deleted"] is True


def test_project_patch_settings(server_app, homes):
    url = server_app.url
    root, pid = _make_project(url, homes)
    r = requests.patch(
        f"{url}/api/projects/{pid}",
        json={"name": "Renamed Project", "settings": {"permission_mode": "plan", "model": "claude-opus-4-8"}},
        timeout=5,
    )
    assert r.status_code == 200
    assert r.json()["name"] == "Renamed Project"
    on_disk = json.loads((root / ".orchid" / "project.json").read_text())
    assert on_disk["settings"]["permission_mode"] == "plan"
    assert on_disk["settings"]["model"] == "claude-opus-4-8"
