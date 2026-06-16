"""In-process MCP tools for git operations during orchestrator sessions.

Same pattern as planning.py: tools defined here, wired via mcp_servers +
allowed_tools, mutations publish events so the UI updates live.
"""

import fnmatch
import re
from pathlib import Path
from typing import Any

from claude_agent_sdk import create_sdk_mcp_server, tool

from ..bus import EventBus
from ..git_ops import changed_files, diff_stat_lines, merge_branch, run_git
from ..store import policy_store, project_store

GIT_SERVER = "orchid_git"
_TOOLS = [
    "create_branch", "git_status", "git_commit", "git_diff",
    "check_gates", "report_gate_results", "request_review", "merge_branch",
]
GIT_TOOL_NAMES = [f"mcp__{GIT_SERVER}__{t}" for t in _TOOLS]

_BRANCH_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._/-]*$")
_MAX_DIFF = 50_000

_GATE_LABELS = {
    "tests_pass": "Run the project's test suite and report pass/fail",
    "spec_compliance": "Verify changes are consistent with the living specification",
    "diff_budget": "Total diff must not exceed the line budget",
    "no_new_deps": "Flag any newly added dependencies",
    "sensitive_files": "Check for changes to sensitive file patterns",
    "acceptance_criteria": "Evaluate against the project's acceptance criteria",
}


def _text(s: str, is_error: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {"content": [{"type": "text", "text": s}]}
    if is_error:
        out["is_error"] = True
    return out


def build_git_tools(root: Path, project_id: str, bus: EventBus, notifier: Any = None) -> list[Any]:

    gate_results: dict[str, dict[str, Any]] = {}

    @tool("create_branch", "Create and switch to a new branch from the current HEAD.",
          {"branch_name": str})
    async def create_branch(args: dict[str, Any]) -> dict[str, Any]:
        name = (args.get("branch_name") or "").strip()
        if not name or not _BRANCH_RE.match(name):
            return _text(f"Invalid branch name: {name!r}. Use alphanumeric, dots, hyphens, slashes.", is_error=True)
        rc, out = await run_git(root, "checkout", "-b", name)
        if rc != 0:
            return _text(f"git checkout -b failed:\n{out}", is_error=True)
        return _text(f"Created and switched to branch '{name}'.")

    @tool("git_status", "Show current branch and working tree status.", {})
    async def git_status(_args: dict[str, Any]) -> dict[str, Any]:
        _, branch = await run_git(root, "branch", "--show-current")
        _, status = await run_git(root, "status", "--short")
        return _text(f"branch: {branch.strip()}\n{status.strip() or '(clean)'}")

    @tool("git_commit", "Stage files and commit. paths = newline-separated list (or '.' for all).",
          {"message": str, "paths": str})
    async def git_commit(args: dict[str, Any]) -> dict[str, Any]:
        msg = (args.get("message") or "").strip()
        if not msg:
            return _text("Commit message is required.", is_error=True)
        paths = (args.get("paths") or ".").strip()
        add_args = paths.split("\n") if "\n" in paths else [paths]
        rc, out = await run_git(root, "add", *[p.strip() for p in add_args if p.strip()])
        if rc != 0:
            return _text(f"git add failed:\n{out}", is_error=True)
        rc, out = await run_git(root, "commit", "-m", msg)
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
        rc, out = await run_git(root, *cmd)
        if rc != 0:
            return _text(f"git diff failed:\n{out}", is_error=True)
        if not out.strip():
            return _text("(no changes)")
        if len(out) > _MAX_DIFF:
            out = out[:_MAX_DIFF] + f"\n\n… truncated ({len(out)} chars total)"
        return _text(out)

    @tool("check_gates",
          "Check which quality gates are active for this project and their current status. "
          "Call this before requesting review to see what you need to satisfy.",
          {"branch": str})
    async def check_gates(args: dict[str, Any]) -> dict[str, Any]:
        branch = (args.get("branch") or "").strip()
        policy = policy_store.resolve_policy(root)
        gates = policy.get("gates", {})
        lines = [f"Quality gates for profile '{policy['profile']}':"]

        for gate_name, gate_cfg in gates.items():
            mode = gate_cfg.get("mode", "skip")
            if mode == "skip":
                lines.append(f"  {gate_name} [SKIP]")
                continue

            label = _GATE_LABELS.get(gate_name, gate_name)
            status = "NOT RUN"

            if gate_name == "diff_budget" and branch:
                total = await diff_stat_lines(root, branch)
                budget = gate_cfg.get("max_lines", 500)
                status = f"PASS ({total}/{budget} lines)" if total <= budget else f"FAIL ({total}/{budget} lines)"
            elif gate_name == "sensitive_files" and branch:
                patterns = gate_cfg.get("patterns", [])
                if patterns:
                    files = await changed_files(root, branch)
                    matched = [f for f in files if any(fnmatch.fnmatch(f, p) for p in patterns)]
                    status = f"FAIL (matched: {', '.join(matched)})" if matched else "PASS (no sensitive files touched)"
                else:
                    status = "PASS (no patterns configured)"

            prev = gate_results.get(branch, {}).get(gate_name)
            if prev is not None:
                status = "PASS" if prev.get("passed") else f"FAIL: {prev.get('reason', '')}"

            lines.append(f"  {gate_name} [{mode.upper()}]: {label}. Status: {status}")

        lines.append(f"\nPlan approval: {policy['plan_approval']}")
        lines.append(f"Review strategy: {policy['review_strategy']}")
        lines.append(f"Merge approval: {policy['merge_approval']}")
        return _text("\n".join(lines))

    @tool("report_gate_results",
          "Report the results of quality gate checks. Call after running each gate. "
          "results is a JSON object: {gate_name: {passed: bool, reason: str}, ...}",
          {"branch": str, "results": str})
    async def report_gate_results_tool(args: dict[str, Any]) -> dict[str, Any]:
        branch = (args.get("branch") or "").strip()
        if not branch:
            return _text("Branch name is required.", is_error=True)
        import json
        try:
            results = json.loads(args.get("results") or "{}")
        except json.JSONDecodeError:
            return _text("Invalid JSON in results.", is_error=True)
        if not isinstance(results, dict):
            return _text("Results must be a JSON object.", is_error=True)

        gate_results.setdefault(branch, {}).update(results)

        policy = policy_store.resolve_policy(root)
        gates = policy.get("gates", {})
        failures = []
        missing = []
        for gate_name, gate_cfg in gates.items():
            if gate_cfg.get("mode") != "required":
                continue
            if gate_name in ("diff_budget", "sensitive_files"):
                continue
            result = gate_results.get(branch, {}).get(gate_name)
            if result is None:
                missing.append(gate_name)
            elif not result.get("passed"):
                failures.append(f"{gate_name}: {result.get('reason', 'failed')}")

        parts = []
        if failures:
            parts.append("BLOCKED — required gates failed:\n" + "\n".join(f"  - {f}" for f in failures))
        if missing:
            parts.append("Required gates not yet reported: " + ", ".join(missing))
        if not failures and not missing:
            parts.append("All required gates passed. You may proceed to request_review.")
        return _text("\n".join(parts), is_error=bool(failures))

    @tool("request_review",
          "Submit the current branch for review. Include `verification`: the exact checks you "
          "ran and their output (the verifier's pass/fail report — test/typecheck/lint command + "
          "result), so the reviewer approves against observed evidence, not a claim.",
          {"branch": str, "summary": str, "verification": str})
    async def request_review(args: dict[str, Any]) -> dict[str, Any]:
        branch = (args.get("branch") or "").strip()
        summary = (args.get("summary") or "").strip()
        verification = (args.get("verification") or "").strip()
        if not branch or not summary:
            return _text("Both branch and summary are required.", is_error=True)

        policy = policy_store.resolve_policy(root)
        review_strategy = policy.get("review_strategy", "human")

        file = project_store.read_project_file(root)
        review_mode = (file or {}).get("review_mode", "manual")

        review_id = "rev_" + __import__("secrets").token_hex(6)
        from ..store import review_store
        review_data: dict[str, Any] = {
            "id": review_id, "project_id": project_id, "branch": branch,
            "summary": summary,
            "status": "pending" if review_strategy != "self" else "approved",
            "reviewer_notes": None,
            "verification": verification or None,
            "gate_results": gate_results.get(branch),
            "created_at": __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc).isoformat(),
        }
        review_store.write_review(root, review_data)
        bus.publish("sidebar", "review_requested", {
            "project_id": project_id, "review_id": review_id,
            "branch": branch, "summary": summary,
            "review_mode": review_mode, "review_strategy": review_strategy,
        })
        if notifier is not None and review_strategy == "human":
            notifier.push_bg(
                "Orchid — review requested",
                f"{branch}: {summary}",
                url=notifier.review_url(project_id, review_id),
                url_title="Review in Orchid",
            )
        warn = "" if verification else (
            " No verification evidence was attached — correctness will be treated as "
            "UNCONFIRMED; run the project's checks and resubmit with the output."
        )
        if review_strategy == "self":
            return _text(
                f"Review created (id={review_id}, status=approved). Self-review policy — "
                f"call merge_branch to merge branch '{branch}'.{warn}"
            )
        if review_strategy == "agent":
            return _text(f"Review requested (id={review_id}). The reviewer agent will review branch '{branch}' automatically.{warn}")
        return _text(f"Review requested (id={review_id}). Waiting for manual review of branch '{branch}'.{warn}")

    @tool("merge_branch",
          "Merge a reviewed branch. Only works when the project's merge_approval policy is 'auto' "
          "and the review is approved.",
          {"review_id": str})
    async def merge_branch_tool(args: dict[str, Any]) -> dict[str, Any]:
        review_id = (args.get("review_id") or "").strip()
        if not review_id:
            return _text("review_id is required.", is_error=True)

        policy = policy_store.resolve_policy(root)
        if policy.get("merge_approval") != "auto":
            return _text("Merge approval is set to 'human'. Wait for the human to merge.", is_error=True)

        from ..store import review_store
        review = review_store.read_review(root, review_id)
        if review is None:
            return _text(f"Review {review_id} not found.", is_error=True)
        if review.get("status") not in ("pending", "approved"):
            return _text(f"Review status is '{review.get('status')}' — cannot merge.", is_error=True)

        branch = review.get("branch", "")
        rc, out = await merge_branch(root, branch)
        if rc != 0:
            return _text(f"Merge failed:\n{out}", is_error=True)

        review["status"] = "merged"
        review_store.write_review(root, review)
        bus.publish("sidebar", "review_updated", {
            "project_id": project_id, "review": review,
        })
        return _text(f"Branch '{branch}' merged successfully.")

    return [
        create_branch, git_status, git_commit, git_diff,
        check_gates, report_gate_results_tool, request_review, merge_branch_tool,
    ]


def build_git_server(root: Path, project_id: str, bus: EventBus, notifier: Any = None) -> Any:
    return create_sdk_mcp_server(
        GIT_SERVER, "0.1.0", tools=build_git_tools(root, project_id, bus, notifier),
    )
