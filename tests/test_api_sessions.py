import requests
from claude_agent_sdk import SDKSessionInfo, SessionMessage

from datetime import datetime, timezone

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

    catalog.session_info = session_info
    catalog.session_messages = session_messages
    catalog.subagents = subagents
    catalog.subagent_messages = subagent_messages


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
