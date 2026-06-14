"""Tests for the git MCP tools used by orchestrator sessions."""

import subprocess

import pytest

from orchid.bus import EventBus
from orchid.claude.git_tools import build_git_tools
from orchid.store import project_store


def _text_of(result: dict) -> str:
    return result["content"][0]["text"]


@pytest.fixture
def harness(tmp_path):
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(tmp_path), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(tmp_path), check=True, capture_output=True)
    (tmp_path / "README.md").write_text("# Test\n")
    subprocess.run(["git", "add", "."], cwd=str(tmp_path), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=str(tmp_path), check=True, capture_output=True)
    project_store.init_project(tmp_path, "prj_test", "test")
    bus = EventBus()
    tools = {t.name: t for t in build_git_tools(tmp_path, "prj_test", bus)}
    return tmp_path, bus, tools


@pytest.mark.anyio
async def test_create_branch_and_status(harness):
    root, bus, tools = harness
    out = _text_of(await tools["create_branch"].handler({"branch_name": "feat/hello"}))
    assert "feat/hello" in out
    out = _text_of(await tools["git_status"].handler({}))
    assert "feat/hello" in out


@pytest.mark.anyio
async def test_git_commit(harness):
    root, bus, tools = harness
    await tools["create_branch"].handler({"branch_name": "feat/work"})
    (root / "new.txt").write_text("hello\n")
    out = _text_of(await tools["git_commit"].handler({"message": "add new.txt", "paths": "new.txt"}))
    assert "add new.txt" in out or "1 file changed" in out


@pytest.mark.anyio
async def test_git_diff(harness):
    root, bus, tools = harness
    (root / "README.md").write_text("# Changed\n")
    out = _text_of(await tools["git_diff"].handler({"staged": "", "branch": ""}))
    assert "Changed" in out


@pytest.mark.anyio
async def test_request_review_publishes_event(harness):
    root, bus, tools = harness
    sub = bus.subscribe({"sidebar"})
    await tools["create_branch"].handler({"branch_name": "feat/pr"})
    (root / "x.txt").write_text("x\n")
    await tools["git_commit"].handler({"message": "add x", "paths": "."})
    out = _text_of(await tools["request_review"].handler({"branch": "feat/pr", "summary": "Added x"}))
    assert "rev_" in out
    types = set()
    while not sub.queue.empty():
        types.add(sub.queue.get_nowait()["type"])
    assert "review_requested" in types


@pytest.mark.anyio
async def test_create_branch_bad_name(harness):
    _, _, tools = harness
    out = await tools["create_branch"].handler({"branch_name": "..bad"})
    assert out.get("is_error")
