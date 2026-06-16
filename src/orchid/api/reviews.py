import asyncio
from pathlib import Path

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ..git_ops import changed_files, find_base_branch, merge_branch, run_git, touches_tests
from ..services import ApiError, ProjectService
from ..store import review_store

router = APIRouter()


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
    files = await changed_files(root, review.get("branch", ""))
    return {
        **review,
        "files_changed": len(files),
        "touches_tests": touches_tests(files),
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
    # Merge the branch
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


