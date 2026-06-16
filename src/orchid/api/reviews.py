import asyncio
from pathlib import Path

from fastapi import APIRouter, Request
from pydantic import BaseModel

from datetime import datetime, timezone

from ..git_ops import (
    changed_files, find_base_branch, github_pr_checks, github_pr_state, list_open_prs,
    merge_branch, merge_github_pr, run_branch_command, run_git, touches_tests,
)
from ..services import ApiError, ProjectService
from ..store import project_store, review_store

router = APIRouter()


def _service(request: Request) -> ProjectService:
    return request.app.state.service


@router.get("/projects/{project_id}/reviews")
async def list_reviews(request: Request, project_id: str):
    root = Path(_service(request).get_entry(project_id)["root"])
    reviews = review_store.list_reviews(root)
    # Adopt open GitHub PRs that aren't tracked yet (e.g. raised outside Orchid),
    # so the reviews list reflects every open PR, not just Orchid-created ones.
    tracked = {r.get("pr_number") for r in reviews if r.get("pr_number")}
    new = False
    for pr in await list_open_prs(root):
        if pr.get("number") in tracked:
            continue
        now = datetime.now(timezone.utc).isoformat()
        record = {
            "id": review_store.new_review_id(),
            "project_id": project_id,
            "branch": pr.get("headRefName", ""),
            "summary": pr.get("title", "") or pr.get("headRefName", ""),
            "status": "pending",
            "reviewer_notes": None,
            "verification": None,
            "pr_number": pr.get("number"),
            "pr_url": pr.get("url"),
            "adopted": True,
            "created_at": now,
        }
        review_store.write_review(root, record)
        reviews.append(record)
        new = True
    if new:
        request.app.state.bus.publish(
            "sidebar", "review_updated", {"project_id": project_id})
    return reviews


@router.get("/projects/{project_id}/reviews/{review_id}")
async def get_review(request: Request, project_id: str, review_id: str):
    root = Path(_service(request).get_entry(project_id)["root"])
    review = review_store.read_review(root, review_id)
    if review is None:
        raise ApiError("REVIEW_NOT_FOUND", f"no review {review_id}", 404)
    # Reconcile a PR-backed review with GitHub: if it merged/closed there, resolve
    # it here so a PR merged outside Orchid doesn't sit forever as "pending".
    if review.get("status") == "pending" and review.get("pr_number"):
        state = await github_pr_state(root, review["pr_number"])
        new_status = {"MERGED": "merged", "CLOSED": "changes_requested"}.get(state or "")
        if new_status:
            review["status"] = new_status
            review_store.write_review(root, review)
            request.app.state.bus.publish(
                "sidebar", "review_updated", {"project_id": project_id, "review": review})
    # Enrich (computed on read, never stored, so it always reflects the branch as-is):
    # changed files + test-touch flag (agent-proof), and the PR's CI checks as
    # real verification evidence when the review is PR-backed.
    files = await changed_files(root, review.get("branch", ""))
    ci = await github_pr_checks(root, review["pr_number"]) if review.get("pr_number") else None
    return {
        **review,
        "files_changed": len(files),
        "touches_tests": touches_tests(files),
        "ci": ci,
    }



@router.get("/projects/{project_id}/reviews/{review_id}/diff")
async def review_diff(request: Request, project_id: str, review_id: str):
    root = Path(_service(request).get_entry(project_id)["root"])
    review = review_store.read_review(root, review_id)
    if review is None:
        raise ApiError("REVIEW_NOT_FOUND", f"no review {review_id}", 404)
    branch = review.get("branch", "")
    base = await find_base_branch(root, branch)
    try:
        if base:
            diff_spec = f"{base}...{branch}"
        else:
            rc, root_sha = await run_git(root, "rev-list", "--max-parents=0", branch)
            diff_spec = f"{root_sha.strip()}..{branch}" if rc == 0 else branch
        rc, out = await run_git(root, "diff", diff_spec)
        return {"diff": out if rc == 0 else "(failed to generate diff)"}
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
    # PR-backed review merges on GitHub; local-only review merges the local branch.
    if review.get("pr_number"):
        rc, out = await merge_github_pr(root, review["pr_number"])
    else:
        rc, out = await merge_branch(root, branch)
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


@router.post("/projects/{project_id}/reviews/{review_id}/verify")
async def verify_review(request: Request, project_id: str, review_id: str):
    """Run the project's test command against the review's branch (in a throwaway
    worktree) and attach the output as the review's verification evidence."""
    root = Path(_service(request).get_entry(project_id)["root"])
    review = review_store.read_review(root, review_id)
    if review is None:
        raise ApiError("REVIEW_NOT_FOUND", f"no review {review_id}", 404)
    cmd = project_store.get_test_command(root)
    if not cmd:
        raise ApiError(
            "NO_TEST_COMMAND",
            "No test command configured. Set one in project settings, or document it "
            "in backticks in AGENTS.md.", 400)
    branch = review.get("branch", "")
    rc, out = await run_branch_command(root, branch, cmd)
    status = "PASS" if rc == 0 else "FAIL"
    capped = out if len(out) <= 8000 else "…" + out[-8000:]
    review["verification"] = (
        f"On-demand verification — `{cmd}` on `{branch}`\n"
        f"Exit {rc} ({status})\n\n{capped}"
    )
    review_store.write_review(root, review)
    request.app.state.bus.publish(
        "sidebar", "review_updated", {"project_id": project_id, "review": review})
    return review


