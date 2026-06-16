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
