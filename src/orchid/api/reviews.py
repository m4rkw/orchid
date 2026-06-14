import asyncio
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ..services import ApiError, ProjectService
from ..store import review_store

router = APIRouter()

# Heuristic for "this change touches tests" — used to flag branches where the
# reviewer must confirm tests weren't weakened to pass (reward-hack resistance).
_TEST_PATH_RE = re.compile(r"(^|/)(tests?|spec)/|(_test\.|\.test\.|\.spec\.|conftest\.py$)", re.I)


def _service(request: Request) -> ProjectService:
    return request.app.state.service


@router.get("/projects/{project_id}/reviews")
async def list_reviews(request: Request, project_id: str):
    root = Path(_service(request).get_entry(project_id)["root"])
    return review_store.list_reviews(root)


@router.get("/projects/{project_id}/reviews/{review_id}")
async def get_review(request: Request, project_id: str, review_id: str):
    root = Path(_service(request).get_entry(project_id)["root"])
    review = review_store.read_review(root, review_id)
    if review is None:
        raise ApiError("REVIEW_NOT_FOUND", f"no review {review_id}", 404)
    # Enrich (computed on read, never stored, so it always reflects the branch as-is):
    # which files changed, and whether any are tests — the agent can't fake this.
    files = await _changed_files(root, review.get("branch", ""))
    return {
        **review,
        "files_changed": len(files),
        "touches_tests": any(_TEST_PATH_RE.search(f) for f in files),
    }


async def _changed_files(root: Path, branch: str) -> list[str]:
    if not branch:
        return []
    base = await _find_base_branch(root, branch)
    spec = f"{base}...{branch}" if base else branch
    rc, out = await _run_git(root, "diff", "--name-only", spec)
    return [line.strip() for line in out.splitlines() if line.strip()] if rc == 0 else []


@router.get("/projects/{project_id}/reviews/{review_id}/diff")
async def review_diff(request: Request, project_id: str, review_id: str):
    root = Path(_service(request).get_entry(project_id)["root"])
    review = review_store.read_review(root, review_id)
    if review is None:
        raise ApiError("REVIEW_NOT_FOUND", f"no review {review_id}", 404)
    branch = review.get("branch", "")
    base = await _find_base_branch(root, branch)
    try:
        if base:
            diff_spec = f"{base}...{branch}"
        else:
            # No base branch — show all commits on this branch
            rc, root_sha = await _run_git(root, "rev-list", "--max-parents=0", branch)
            diff_spec = f"{root_sha.strip()}..{branch}" if rc == 0 else branch
        proc = await asyncio.create_subprocess_exec(
            "git", "diff", diff_spec,
            cwd=str(root),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        return {"diff": out.decode(errors="replace")}
    except (OSError, asyncio.TimeoutError):
        return {"diff": "(failed to generate diff)"}


class ReviewAction(BaseModel):
    notes: str | None = None


@router.post("/projects/{project_id}/reviews/{review_id}/approve")
async def approve_review(request: Request, project_id: str, review_id: str, body: ReviewAction):
    root = Path(_service(request).get_entry(project_id)["root"])
    review = review_store.read_review(root, review_id)
    if review is None:
        raise ApiError("REVIEW_NOT_FOUND", f"no review {review_id}", 404)
    branch = review.get("branch", "")
    # Merge the branch
    rc, out = await _merge_branch(root, branch)
    if rc != 0:
        raise ApiError("MERGE_FAILED", f"merge failed: {out}", 500)
    review["status"] = "merged"
    review["reviewer_notes"] = body.notes
    review_store.write_review(root, review)
    bus = request.app.state.bus
    bus.publish("sidebar", "review_updated", {
        "project_id": project_id, "review": review,
    })
    return review


@router.post("/projects/{project_id}/reviews/{review_id}/reject")
async def reject_review(request: Request, project_id: str, review_id: str, body: ReviewAction):
    root = Path(_service(request).get_entry(project_id)["root"])
    review = review_store.read_review(root, review_id)
    if review is None:
        raise ApiError("REVIEW_NOT_FOUND", f"no review {review_id}", 404)
    review["status"] = "changes_requested"
    review["reviewer_notes"] = body.notes
    review_store.write_review(root, review)
    bus = request.app.state.bus
    bus.publish("sidebar", "review_updated", {
        "project_id": project_id, "review": review,
    })
    return review


async def _find_base_branch(root: Path, branch: str) -> str | None:
    """Find the base branch to diff/merge against (main, master, or None)."""
    for candidate in ("main", "master"):
        if candidate == branch:
            continue
        rc, _ = await _run_git(root, "rev-parse", "--verify", candidate)
        if rc == 0:
            return candidate
    return None


async def _merge_branch(root: Path, branch: str) -> tuple[int, str]:
    base = await _find_base_branch(root, branch)
    if not base:
        # No main/master — create main at the root commit, then merge the branch into it
        rc, root_sha = await _run_git(root, "rev-list", "--max-parents=0", branch)
        if rc != 0:
            return 1, "No base branch and couldn't find root commit."
        rc, out = await _run_git(root, "branch", "main", root_sha.strip().split("\n")[0])
        if rc != 0:
            return rc, out
        base = "main"
    rc, out = await _run_git(root, "checkout", base)
    if rc != 0:
        return rc, out
    rc, out = await _run_git(root, "merge", "--no-ff", branch, "-m", f"Merge branch '{branch}'")
    if rc != 0:
        await _run_git(root, "merge", "--abort")
        return rc, out
    await _run_git(root, "branch", "-d", branch)
    return 0, out


async def _run_git(root: Path, *args: str) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        "git", *args, cwd=str(root),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
    return proc.returncode, out.decode(errors="replace")
