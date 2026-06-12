import json

from orchid.store import project_store


def test_init_project_writes_state(tmp_path):
    data = project_store.init_project(tmp_path, "prj_x", "Demo")
    assert data["id"] == "prj_x"
    assert data["name"] == "Demo"
    assert (tmp_path / ".orchid" / ".gitignore").read_text() == "*\n"
    on_disk = json.loads((tmp_path / ".orchid" / "project.json").read_text())
    assert on_disk["settings"]["permission_mode"] == "acceptEdits"


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
