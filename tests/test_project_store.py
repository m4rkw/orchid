import json

from orchid.store import project_store


def test_init_project_writes_state(tmp_path):
    data = project_store.init_project(tmp_path, "prj_x", "Demo")
    assert data["id"] == "prj_x"
    assert data["name"] == "Demo"
    gi = (tmp_path / ".orchid" / ".gitignore").read_text()
    assert "*\n" in gi and "!spec.md" in gi and "!architecture.md" in gi  # docs tracked
    on_disk = json.loads((tmp_path / ".orchid" / "project.json").read_text())
    assert on_disk["settings"]["permission_mode"] == "acceptEdits"


def test_writing_a_spec_untracks_only_docs(tmp_path):
    from orchid.store import spec_store
    project_store.init_project(tmp_path, "prj_gi", "GI")
    spec_store.write_spec(tmp_path, {"version": 1, "title": "S", "content": "x", "status": "active"})
    gi = (tmp_path / ".orchid" / ".gitignore").read_text()
    # docs un-ignored; everything else (plans/reviews/sessions/usage) still ignored
    assert "!spec.md" in gi and "!architecture.md" in gi
    assert "!sessions.json" not in gi and "!plans" not in gi


def test_init_project_is_idempotent(tmp_path):
    first = project_store.init_project(tmp_path, "prj_x", "Demo")
    second = project_store.init_project(tmp_path, "prj_y", "Other")
    assert second["id"] == "prj_x"  # existing identity wins
    assert second["name"] == first["name"]


def test_session_flags_sparse_upsert(tmp_path):
    assert project_store.get_session_flags(tmp_path) == {}
    project_store.set_session_flags(tmp_path, "sid-1", pinned=True, created_by="orchid")
    flags = project_store.get_session_flags(tmp_path)
    assert flags["sid-1"]["pinned"] is True
    assert flags["sid-1"]["created_by"] == "orchid"
    assert "first_seen_at" in flags["sid-1"]
    project_store.set_session_flags(tmp_path, "sid-1", pinned=False)
    assert project_store.get_session_flags(tmp_path)["sid-1"]["pinned"] is False
    assert project_store.get_session_flags(tmp_path)["sid-1"]["created_by"] == "orchid"


def test_get_test_command_from_settings(tmp_path):
    project_store.init_project(tmp_path, "prj_tc", "TC")
    f = project_store.read_project_file(tmp_path)
    f.setdefault("settings", {})["test_command"] = "uv run pytest -q"
    project_store.write_project_file(tmp_path, f)
    assert project_store.get_test_command(tmp_path) == "uv run pytest -q"


def test_get_test_command_from_agents_md(tmp_path):
    project_store.init_project(tmp_path, "prj_tc2", "TC2")
    (tmp_path / "AGENTS.md").write_text("Run tests with `python3 -m unittest discover -s tests`.")
    assert project_store.get_test_command(tmp_path) == "python3 -m unittest discover -s tests"


def test_get_test_command_none(tmp_path):
    project_store.init_project(tmp_path, "prj_tc3", "TC3")
    assert project_store.get_test_command(tmp_path) is None
