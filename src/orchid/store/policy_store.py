"""Autonomy policy per project at <root>/.orchid/policy.json.

Controls how much human involvement is required at each stage of the
orchestrator workflow: plan approval, quality gates, review strategy,
and merge approval.  Three presets (permissive / balanced / strict)
cover the common cases; any field can be overridden for a custom policy.
"""

from pathlib import Path
from typing import Any

from .jsonio import atomic_write_json, load_json
from .project_store import orchid_dir

PRESETS: dict[str, dict[str, Any]] = {
    "permissive": {
        "profile": "permissive",
        "plan_approval": "auto",
        "review_strategy": "self",
        "merge_approval": "auto",
        "gates": {
            "tests_pass": {"mode": "optional"},
            "spec_compliance": {"mode": "skip"},
            "diff_budget": {"mode": "skip", "max_lines": 500},
            "no_new_deps": {"mode": "skip"},
            "sensitive_files": {"mode": "skip", "patterns": []},
            "acceptance_criteria": {"mode": "skip", "criteria": ""},
        },
    },
    "balanced": {
        "profile": "balanced",
        "plan_approval": "auto",
        "review_strategy": "agent",
        "merge_approval": "auto",
        "gates": {
            "tests_pass": {"mode": "required"},
            "spec_compliance": {"mode": "required"},
            "diff_budget": {"mode": "skip", "max_lines": 500},
            "no_new_deps": {"mode": "optional"},
            "sensitive_files": {"mode": "skip", "patterns": []},
            "acceptance_criteria": {"mode": "skip", "criteria": ""},
        },
    },
    "strict": {
        "profile": "strict",
        "plan_approval": "human",
        "review_strategy": "human",
        "merge_approval": "human",
        "gates": {
            "tests_pass": {"mode": "required"},
            "spec_compliance": {"mode": "required"},
            "diff_budget": {"mode": "required", "max_lines": 300},
            "no_new_deps": {"mode": "required"},
            "sensitive_files": {"mode": "required", "patterns": []},
            "acceptance_criteria": {"mode": "skip", "criteria": ""},
        },
    },
}

DEFAULT_PRESET = "balanced"


def policy_path(root: Path) -> Path:
    return orchid_dir(root) / "policy.json"


def read_policy(root: Path) -> dict[str, Any] | None:
    data = load_json(policy_path(root), default=None)
    return data if isinstance(data, dict) and data.get("profile") else None


def write_policy(root: Path, policy: dict[str, Any]) -> None:
    path = policy_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, {**policy, "version": policy.get("version", 1)})


def resolve_policy(root: Path) -> dict[str, Any]:
    """Return the effective policy: explicit policy.json > legacy review_mode > balanced default."""
    stored = read_policy(root)
    if stored is not None:
        base = dict(PRESETS[DEFAULT_PRESET])
        base["gates"] = dict(base["gates"])
        base.update({k: v for k, v in stored.items() if k != "gates"})
        if "gates" in stored:
            base["gates"].update(stored["gates"])
        return base

    from .project_store import read_project_file
    proj = read_project_file(root) or {}
    review_mode = proj.get("review_mode")
    if review_mode == "manual":
        policy = dict(PRESETS["balanced"])
        policy["review_strategy"] = "human"
        return policy
    if review_mode == "autonomous":
        return dict(PRESETS["balanced"])

    return dict(PRESETS[DEFAULT_PRESET])
