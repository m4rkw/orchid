import json

from orchid.store import agents_store, plan_store


def test_agent_overrides_roundtrip(tmp_path):
    assert agents_store.read_agent_overrides(tmp_path) == {}
    agents_store.write_agent_overrides(
        tmp_path, {"worker": {"enabled": False}, "verifier": {"model": "claude-haiku-4-5"}}
    )
    roles = agents_store.read_agent_overrides(tmp_path)
    assert roles["worker"]["enabled"] is False
    assert roles["verifier"]["model"] == "claude-haiku-4-5"
    on_disk = json.loads((tmp_path / ".orchid" / "agents.json").read_text())
    assert on_disk["version"] == 1


def test_plan_crud_roundtrip(tmp_path):
    assert plan_store.list_plans(tmp_path) == []
    pid = plan_store.new_plan_id()
    plan = {
        "version": 1,
        "id": pid,
        "title": "Ship feature",
        "goal": "Deliver X",
        "status": "active",
        "steps": [{"id": plan_store.new_step_id(), "title": "step 1", "status": "pending", "roles": ["worker"]}],
        "created_at": "2026-06-12T00:00:00+00:00",
        "updated_at": "2026-06-12T00:00:00+00:00",
    }
    plan_store.write_plan(tmp_path, plan)
    assert plan_store.read_plan(tmp_path, pid)["title"] == "Ship feature"
    assert [p["id"] for p in plan_store.list_plans(tmp_path)] == [pid]
    assert plan_store.delete_plan(tmp_path, pid) is True
    assert plan_store.read_plan(tmp_path, pid) is None
    assert plan_store.delete_plan(tmp_path, pid) is False


def test_plan_id_is_path_safe(tmp_path):
    # ids arrive from URLs/tool args; traversal or junk must not read/write outside the dir
    assert plan_store.read_plan(tmp_path, "../../etc/passwd") is None
    assert plan_store.read_plan(tmp_path, "not-a-plan") is None
    assert plan_store.delete_plan(tmp_path, "../evil") is False
    try:
        plan_store.write_plan(tmp_path, {"id": "../evil", "title": "x"})
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_list_plans_sorted_by_updated_desc(tmp_path):
    for pid, ts in [("pln_aaaaaa", "2026-06-10T00:00:00+00:00"), ("pln_bbbbbb", "2026-06-12T00:00:00+00:00")]:
        plan_store.write_plan(tmp_path, {"version": 1, "id": pid, "title": pid, "updated_at": ts})
    assert [p["id"] for p in plan_store.list_plans(tmp_path)] == ["pln_bbbbbb", "pln_aaaaaa"]
