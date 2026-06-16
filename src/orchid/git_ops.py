"""Shared async git operations used by both the REST API and MCP tools.

Pure git — no SDK imports.  Both api/reviews.py and claude/git_tools.py
call these rather than duplicating subprocess wrappers.
"""

import asyncio
import re
from pathlib import Path

_TEST_PATH_RE = re.compile(
    r"(^|/)(tests?|spec)/|(_test\.|\.test\.|\.spec\.|conftest\.py$)", re.I,
)


async def run_git(root: Path, *args: str, timeout: float = 30) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        "git", *args, cwd=str(root),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    return proc.returncode, out.decode(errors="replace")


async def find_base_branch(root: Path, branch: str) -> str | None:
    """Find the base branch to diff/merge against (main, master, or None)."""
    for candidate in ("main", "master"):
        if candidate == branch:
            continue
        rc, _ = await run_git(root, "rev-parse", "--verify", candidate)
        if rc == 0:
            return candidate
    return None


async def merge_branch(root: Path, branch: str) -> tuple[int, str]:
    """Merge a feature branch into its base (main/master), creating main if needed."""
    base = await find_base_branch(root, branch)
    if not base:
        rc, root_sha = await run_git(root, "rev-list", "--max-parents=0", branch)
        if rc != 0:
            return 1, "No base branch and couldn't find root commit."
        rc, out = await run_git(root, "branch", "main", root_sha.strip().split("\n")[0])
        if rc != 0:
            return rc, out
        base = "main"
    rc, out = await run_git(root, "checkout", base)
    if rc != 0:
        return rc, out
    rc, out = await run_git(root, "merge", "--no-ff", branch, "-m", f"Merge branch '{branch}'")
    if rc != 0:
        await run_git(root, "merge", "--abort")
        return rc, out
    await run_git(root, "branch", "-d", branch)
    return 0, out


async def changed_files(root: Path, branch: str) -> list[str]:
    """List files changed on a branch relative to its base."""
    if not branch:
        return []
    base = await find_base_branch(root, branch)
    spec = f"{base}...{branch}" if base else branch
    rc, out = await run_git(root, "diff", "--name-only", spec)
    return [line.strip() for line in out.splitlines() if line.strip()] if rc == 0 else []


async def diff_stat_lines(root: Path, branch: str) -> int:
    """Count total added+removed lines on a branch relative to its base."""
    if not branch:
        return 0
    base = await find_base_branch(root, branch)
    spec = f"{base}...{branch}" if base else branch
    rc, out = await run_git(root, "diff", "--stat", spec)
    if rc != 0:
        return 0
    for line in reversed(out.splitlines()):
        line = line.strip()
        if "changed" in line:
            total = 0
            if "insertion" in line:
                part = line.split("insertion")[0].rsplit(",", 1)[-1]
                total += int("".join(c for c in part if c.isdigit()) or "0")
            if "deletion" in line:
                part = line.split("deletion")[0].rsplit(",", 1)[-1]
                total += int("".join(c for c in part if c.isdigit()) or "0")
            return total
    return 0


def touches_tests(files: list[str]) -> bool:
    return any(_TEST_PATH_RE.search(f) for f in files)


# -- GitHub PR integration --------------------------------------------------
# When a repo has a GitHub remote, an Orchid review is backed by a real PR
# (opened/merged via `gh`) instead of a local-only branch merge, so the two
# don't diverge. All best-effort: any failure falls back to the local flow.


async def run(root: Path, *args: str, timeout: float = 120) -> tuple[int, str]:
    """Run an arbitrary command (e.g. `gh`, `git push`) and capture output."""
    proc = await asyncio.create_subprocess_exec(
        *args, cwd=str(root),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    return proc.returncode, out.decode(errors="replace")


async def open_github_pr(root: Path, branch: str, summary: str,
                         verification: str = "") -> dict | None:
    """Push `branch` and open (or find) its GitHub PR. Returns {number,url,state}
    or None when there's no GitHub remote or any step fails."""
    try:
        rc, url = await run_git(root, "remote", "get-url", "origin")
        if rc != 0 or "github" not in url.lower():
            return None
        rc, _ = await run(root, "git", "push", "-u", "origin", branch)
        if rc != 0:
            return None
        title = (summary.splitlines()[0] if summary.strip() else branch)[:120]
        body = summary + (f"\n\n## Verification\n\n{verification}" if verification else "")
        # rc may be non-zero if a PR already exists; `pr view` resolves it either way.
        await run(root, "gh", "pr", "create", "--head", branch, "--title", title, "--body", body)
        rc, j = await run(root, "gh", "pr", "view", branch, "--json", "number,url,state")
        if rc != 0:
            return None
        import json
        d = json.loads(j)
        return {"number": d.get("number"), "url": d.get("url"), "state": d.get("state")}
    except Exception:
        return None


async def merge_github_pr(root: Path, pr_number: int) -> tuple[int, str]:
    return await run(root, "gh", "pr", "merge", str(pr_number), "--merge", "--delete-branch")


async def list_open_prs(root: Path) -> list[dict]:
    """Open GitHub PRs for this repo, or [] when there's no GitHub remote / gh
    fails. Used to adopt PRs raised outside Orchid into the reviews list."""
    try:
        rc, url = await run_git(root, "remote", "get-url", "origin")
        if rc != 0 or "github" not in url.lower():
            return []
        rc, j = await run(root, "gh", "pr", "list", "--state", "open",
                          "--json", "number,url,title,headRefName")
        if rc != 0:
            return []
        import json
        data = json.loads(j)
        return data if isinstance(data, list) else []
    except Exception:
        return []


async def github_pr_state(root: Path, pr_number: int) -> str | None:
    """OPEN / MERGED / CLOSED, or None if it can't be determined."""
    try:
        rc, j = await run(root, "gh", "pr", "view", str(pr_number), "--json", "state")
        if rc != 0:
            return None
        import json
        return json.loads(j).get("state")
    except Exception:
        return None


async def github_pr_checks(root: Path, pr_number: int) -> dict | None:
    """Summarise a PR's CI checks (statusCheckRollup) as verification evidence.
    Returns {total,passed,failed,pending,state,lines} or None when there are no
    checks / no remote."""
    try:
        rc, j = await run(root, "gh", "pr", "view", str(pr_number), "--json", "statusCheckRollup")
        if rc != 0:
            return None
        import json
        rollup = json.loads(j).get("statusCheckRollup") or []
        if not rollup:
            return None
        passed = failed = pending = 0
        lines = []
        for c in rollup:
            name = c.get("name") or c.get("context") or "check"
            res = (c.get("conclusion") or c.get("state") or "").upper()
            status = (c.get("status") or "").upper()
            if res in ("SUCCESS", "NEUTRAL", "SKIPPED"):
                passed += 1; mark = "✓"
            elif res in ("FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE"):
                failed += 1; mark = "✗"
            else:  # PENDING/QUEUED/IN_PROGRESS or COMPLETED-without-conclusion
                pending += 1; mark = "•"
            _ = status
            lines.append(f"{mark} {name}" + (f" ({res.lower()})" if res else ""))
        state = "failed" if failed else ("pending" if pending else "passed")
        return {"total": len(rollup), "passed": passed, "failed": failed,
                "pending": pending, "state": state, "lines": lines}
    except Exception:
        return None


async def run_branch_command(root: Path, branch: str, command: str,
                             timeout: float = 600) -> tuple[int, str]:
    """Run a shell command against a branch in a throwaway git worktree, so it
    never disturbs the main working tree or an active session. Returns (rc, output)."""
    import shutil
    import tempfile
    wt = tempfile.mkdtemp(prefix="orchid-verify-")
    try:
        rc, out = await run_git(root, "worktree", "add", "--detach", wt, branch)
        if rc != 0:
            return rc, f"could not create worktree for '{branch}':\n{out}"
        return await run(Path(wt), "sh", "-c", command, timeout=timeout)
    finally:
        await run_git(root, "worktree", "remove", "--force", wt)
        shutil.rmtree(wt, ignore_errors=True)
