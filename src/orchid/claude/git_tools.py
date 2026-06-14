"""In-process MCP tools for git operations during orchestrator sessions.

Same pattern as planning.py: tools defined here, wired via mcp_servers +
allowed_tools, mutations publish events so the UI updates live.
"""

import asyncio
import re
from pathlib import Path
from typing import Any

from claude_agent_sdk import create_sdk_mcp_server, tool

from ..bus import EventBus
from ..store import project_store

GIT_SERVER = "orchid_git"
_TOOLS = ["create_branch", "git_status", "git_commit", "git_diff", "request_review"]
GIT_TOOL_NAMES = [f"mcp__{GIT_SERVER}__{t}" for t in _TOOLS]

_BRANCH_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._/-]*$")
_MAX_DIFF = 50_000


def _text(s: str, is_error: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {"content": [{"type": "text", "text": s}]}
    if is_error:
        out["is_error"] = True
    return out


async def _run_git(root: Path, *args: str, timeout: float = 30) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        "git", *args, cwd=str(root),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    return proc.returncode, out.decode(errors="replace")


def build_git_tools(root: Path, project_id: str, bus: EventBus, notifier: Any = None) -> list[Any]:

    @tool("create_branch", "Create and switch to a new branch from the current HEAD.",
          {"branch_name": str})
    async def create_branch(args: dict[str, Any]) -> dict[str, Any]:
        name = (args.get("branch_name") or "").strip()
        if not name or not _BRANCH_RE.match(name):
            return _text(f"Invalid branch name: {name!r}. Use alphanumeric, dots, hyphens, slashes.", is_error=True)
        rc, out = await _run_git(root, "checkout", "-b", name)
        if rc != 0:
            return _text(f"git checkout -b failed:\n{out}", is_error=True)
        return _text(f"Created and switched to branch '{name}'.")

    @tool("git_status", "Show current branch and working tree status.", {})
    async def git_status(_args: dict[str, Any]) -> dict[str, Any]:
        _, branch = await _run_git(root, "branch", "--show-current")
        _, status = await _run_git(root, "status", "--short")
        return _text(f"branch: {branch.strip()}\n{status.strip() or '(clean)'}")

    @tool("git_commit", "Stage files and commit. paths = newline-separated list (or '.' for all).",
          {"message": str, "paths": str})
    async def git_commit(args: dict[str, Any]) -> dict[str, Any]:
        msg = (args.get("message") or "").strip()
        if not msg:
            return _text("Commit message is required.", is_error=True)
        paths = (args.get("paths") or ".").strip()
        add_args = paths.split("\n") if "\n" in paths else [paths]
        rc, out = await _run_git(root, "add", *[p.strip() for p in add_args if p.strip()])
        if rc != 0:
            return _text(f"git add failed:\n{out}", is_error=True)
        rc, out = await _run_git(root, "commit", "-m", msg)
        if rc != 0:
            return _text(f"git commit failed:\n{out}", is_error=True)
        return _text(out.strip())

    @tool("git_diff", "Show a diff. staged='true' for staged changes, branch='main' to diff against a branch.",
          {"staged": str, "branch": str})
    async def git_diff(args: dict[str, Any]) -> dict[str, Any]:
        cmd: list[str] = ["diff"]
        branch = (args.get("branch") or "").strip()
        if branch:
            cmd.append(f"{branch}...HEAD")
        elif (args.get("staged") or "").strip().lower() == "true":
            cmd.append("--staged")
        rc, out = await _run_git(root, *cmd)
        if rc != 0:
            return _text(f"git diff failed:\n{out}", is_error=True)
        if not out.strip():
            return _text("(no changes)")
        if len(out) > _MAX_DIFF:
            out = out[:_MAX_DIFF] + f"\n\n… truncated ({len(out)} chars total)"
        return _text(out)

    @tool("request_review",
          "Submit the current branch for review. Include `verification`: the exact checks you "
          "ran and their output (the verifier's pass/fail report — test/typecheck/lint command + "
          "result), so the reviewer approves against observed evidence, not a claim. The review "
          "goes to a human or reviewer agent depending on the project's review_mode.",
          {"branch": str, "summary": str, "verification": str})
    async def request_review(args: dict[str, Any]) -> dict[str, Any]:
        branch = (args.get("branch") or "").strip()
        summary = (args.get("summary") or "").strip()
        verification = (args.get("verification") or "").strip()
        if not branch or not summary:
            return _text("Both branch and summary are required.", is_error=True)
        file = project_store.read_project_file(root)
        review_mode = (file or {}).get("review_mode", "manual")
        review_id = "rev_" + __import__("secrets").token_hex(6)
        from ..store import review_store
        review_store.write_review(root, {
            "id": review_id, "project_id": project_id, "branch": branch,
            "summary": summary, "status": "pending", "reviewer_notes": None,
            "verification": verification or None,
            "created_at": __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc).isoformat(),
        })
        bus.publish("sidebar", "review_requested", {
            "project_id": project_id, "review_id": review_id,
            "branch": branch, "summary": summary, "review_mode": review_mode,
        })
        if notifier is not None and review_mode != "autonomous":
            __import__("asyncio").create_task(notifier.push(
                "Orchid — review requested",
                f"{branch}: {summary}",
                url=notifier.review_url(project_id, review_id),
                url_title="Review in Orchid",
            ))
        warn = "" if verification else (
            " No verification evidence was attached — correctness will be treated as "
            "UNCONFIRMED; run the project's checks and resubmit with the output."
        )
        if review_mode == "autonomous":
            return _text(f"Review requested (id={review_id}). The reviewer agent will review branch '{branch}' automatically.{warn}")
        return _text(f"Review requested (id={review_id}). Waiting for manual review of branch '{branch}'.{warn}")

    return [create_branch, git_status, git_commit, git_diff, request_review]


def build_git_server(root: Path, project_id: str, bus: EventBus, notifier: Any = None) -> Any:
    return create_sdk_mcp_server(
        GIT_SERVER, "0.1.0", tools=build_git_tools(root, project_id, bus, notifier),
    )
