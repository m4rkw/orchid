from orchid.claude import roles
from orchid.store import agents_store, policy_store, project_store


def test_builtins_shape():
    by_slug = {r.slug: r for r in roles.BUILTIN_ROLES}
    assert by_slug["orchestrator"].kind == "orchestrator"
    enabled_subagents = {r.slug for r in roles.BUILTIN_ROLES if r.kind == "subagent" and r.enabled}
    assert enabled_subagents == {"worker", "reviewer", "verifier"}
    infra = [r for r in roles.BUILTIN_ROLES if r.kind == "infra"]
    assert len(infra) == 4 and all(not r.enabled and r.note for r in infra)


def test_assemble_default(tmp_path):
    agents, prompt = roles.assemble_orchestrator(tmp_path)
    assert set(agents) == {"worker", "reviewer", "verifier"}
    # reviewer/verifier can't edit; worker inherits tools
    assert "Edit" in (agents["reviewer"].disallowedTools or [])
    assert agents["worker"].tools is None
    # the append carries the orchestrator role, the roster, and planner instructions
    assert "orchestrator for this project" in prompt
    assert "- worker:" in prompt and "Task tool" in prompt
    assert "create_plan" in prompt
    assert "AGENTS.md" not in prompt  # none on disk yet


def test_assemble_embeds_agents_md(tmp_path):
    (tmp_path / "AGENTS.md").write_text("# MyProj\nRun tests with `uv run pytest`.")
    _agents, prompt = roles.assemble_orchestrator(tmp_path)
    assert "Project context (AGENTS.md)" in prompt
    assert "uv run pytest" in prompt


def test_assemble_embeds_project_goal(tmp_path):
    project_store.init_project(tmp_path, "prj_g", "Goalful")
    pf = project_store.read_project_file(tmp_path)
    pf["intent"], pf["goal"], pf["review_mode"] = "goal", "users can sign up and track vehicles", "autonomous"
    project_store.write_project_file(tmp_path, pf)
    _agents, prompt = roles.assemble_orchestrator(tmp_path)
    assert "Project goal" in prompt
    assert "users can sign up and track vehicles" in prompt
    assert "goal-oriented" in prompt and "autonomous" in prompt


def test_assemble_no_goal_section_when_unset(tmp_path):
    project_store.init_project(tmp_path, "prj_n", "Goalless")  # goal stays None
    _agents, prompt = roles.assemble_orchestrator(tmp_path)
    assert "Project goal" not in prompt


def test_assemble_always_states_spec_rule(tmp_path):
    # Standing rule for every orchestrator: even with no spec on disk, the agent
    # is told the spec is a living document it must create and maintain.
    _agents, prompt = roles.assemble_orchestrator(tmp_path)
    assert "living specification" in prompt and "update_spec" in prompt
    assert "Project specification (v" not in prompt  # no spec content embedded yet


def test_assemble_embeds_spec_when_present(tmp_path):
    from orchid.store import spec_store
    spec_store.write_spec(tmp_path, {
        "version": 3, "title": "S", "content": "Build a thing.", "status": "active",
    })
    _agents, prompt = roles.assemble_orchestrator(tmp_path)
    assert "living specification" in prompt          # rule still present
    assert "Project specification (v3)" in prompt    # content embedded
    assert "Build a thing." in prompt


def test_overrides_disable_and_edit(tmp_path):
    agents_store.write_agent_overrides(
        tmp_path, {"worker": {"enabled": False}, "verifier": {"model": "claude-haiku-4-5"}}
    )
    resolved = {r.slug: r for r in roles.resolve_roles(tmp_path)}
    assert resolved["worker"].enabled is False
    assert resolved["verifier"].model == "claude-haiku-4-5"
    agents, _prompt = roles.assemble_orchestrator(tmp_path)
    assert "worker" not in agents  # disabled -> not materialized
    assert agents["verifier"].model == "claude-haiku-4-5"


def test_assemble_with_children(tmp_path):
    child1 = tmp_path / "child1"
    child2 = tmp_path / "child2"
    child1.mkdir()
    child2.mkdir()
    (child1 / "AGENTS.md").write_text("# WebUI\nFrontend service.")
    (child2 / "AGENTS.md").write_text("# API\nBackend service.")
    _agents, prompt = roles.assemble_orchestrator(tmp_path, child_roots=[child1, child2])
    assert "Child project: child1" in prompt
    assert "Frontend service." in prompt
    assert "Child project: child2" in prompt
    assert "Backend service." in prompt


def test_assemble_children_skips_missing_agents_md(tmp_path):
    child = tmp_path / "nochild"
    child.mkdir()
    _agents, prompt = roles.assemble_orchestrator(tmp_path, child_roots=[child])
    assert "Child project" not in prompt


def test_assemble_includes_policy_section(tmp_path):
    project_store.init_project(tmp_path, "prj_p", "Policied")
    policy_store.write_policy(tmp_path, policy_store.PRESETS["strict"])
    _agents, prompt = roles.assemble_orchestrator(tmp_path)
    assert "Autonomy policy" in prompt
    assert "strict" in prompt
    assert "HUMAN REQUIRED" in prompt
    assert "check_gates" in prompt


def test_assemble_default_policy_is_balanced(tmp_path):
    _agents, prompt = roles.assemble_orchestrator(tmp_path)
    assert "balanced" in prompt
    assert "Plan approval: auto" in prompt
    assert "Review: agent" in prompt


def test_assemble_permissive_policy(tmp_path):
    project_store.init_project(tmp_path, "prj_perm", "Hobby")
    policy_store.write_policy(tmp_path, policy_store.PRESETS["permissive"])
    _agents, prompt = roles.assemble_orchestrator(tmp_path)
    assert "permissive" in prompt
    assert "Review: self" in prompt
    assert "Merge: auto" in prompt


def test_normalize_overrides_keeps_only_deltas():
    payload = [
        {"slug": "worker", "enabled": True, "prompt": roles._BUILTIN_BY_SLUG["worker"].prompt},  # unchanged
        {"slug": "verifier", "enabled": False, "model": "claude-haiku-4-5"},  # changed
        {"slug": "bogus", "enabled": True},  # unknown -> dropped
    ]
    out = roles.normalize_overrides(payload)
    assert out == {"verifier": {"enabled": False, "model": "claude-haiku-4-5"}}
