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
async def test_request_review_persists_verification(harness):
    root, bus, tools = harness
    await tools["create_branch"].handler({"branch_name": "feat/v"})
    (root / "y.txt").write_text("y\n")
    await tools["git_commit"].handler({"message": "add y", "paths": "."})
    out = _text_of(await tools["request_review"].handler({
        "branch": "feat/v", "summary": "Added y",
        "verification": "uv run pytest -q\n42 passed",
    }))
    assert "rev_" in out and "UNCONFIRMED" not in out
    from orchid.store import review_store
    reviews = review_store.list_reviews(root)
    assert reviews and reviews[0]["verification"] == "uv run pytest -q\n42 passed"


@pytest.mark.anyio
async def test_request_review_warns_without_verification(harness):
    root, bus, tools = harness
    await tools["create_branch"].handler({"branch_name": "feat/nov"})
    (root / "z.txt").write_text("z\n")
    await tools["git_commit"].handler({"message": "add z", "paths": "."})
    out = _text_of(await tools["request_review"].handler({"branch": "feat/nov", "summary": "Added z"}))
    assert "UNCONFIRMED" in out
    from orchid.store import review_store
    assert review_store.list_reviews(root)[0]["verification"] is None


@pytest.mark.anyio
async def test_request_review_no_remote_is_local(harness):
    root, bus, tools = harness
    await tools["create_branch"].handler({"branch_name": "feat/local"})
    (root / "q.txt").write_text("q\n")
    await tools["git_commit"].handler({"message": "add q", "paths": "."})
    out = _text_of(await tools["request_review"].handler(
        {"branch": "feat/local", "summary": "Add q", "verification": "ok"}))
    assert "rev_" in out and "Opened PR" not in out  # no GitHub remote -> local review
    from orchid.store import review_store
    r = review_store.list_reviews(root)[0]
    assert r.get("pr_number") is None and r.get("pr_url") is None


@pytest.mark.anyio
async def test_open_github_pr_no_remote_returns_none(tmp_path):
    import subprocess
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    from orchid.git_ops import open_github_pr
    assert await open_github_pr(tmp_path, "br", "summary") is None


def test_test_path_heuristic():
    from orchid.git_ops import touches_tests
    for p in ["tests/test_x.py", "src/foo_test.go", "a/b.test.ts",
              "spec/thing_spec.rb", "conftest.py", "pkg/spec/helper.js"]:
        assert touches_tests([p]), f"should match: {p}"
    for p in ["src/main.py", "README.md", "lib/contest.py", "specimen.py"]:
        assert not touches_tests([p]), f"should NOT match: {p}"


@pytest.mark.anyio
async def test_create_branch_bad_name(harness):
    _, _, tools = harness
    out = await tools["create_branch"].handler({"branch_name": "..bad"})
    assert out.get("is_error")
