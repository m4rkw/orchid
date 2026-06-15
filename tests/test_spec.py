"""Tests for the living spec store and API."""

import requests

from orchid.store import spec_store, project_store


def test_spec_store_roundtrip(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    project_store.init_project(root, "prj_test", "test-project")

    assert spec_store.read_spec(root) is None

    spec = {
        "version": 1,
        "title": "My Spec",
        "content": "# Overview\n\nThis project does X.",
        "status": "active",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }
    spec_store.write_spec(root, spec)

    loaded = spec_store.read_spec(root)
    assert loaded is not None
    assert loaded["title"] == "My Spec"
    assert loaded["version"] == 1
    assert "# Overview" in loaded["content"]


def test_spec_store_update(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    project_store.init_project(root, "prj_test", "test-project")

    spec = {
        "version": 1,
        "title": "Spec",
        "content": "v1 content",
        "status": "active",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }
    spec_store.write_spec(root, spec)

    spec["version"] = 2
    spec["content"] = "v2 content"
    spec_store.write_spec(root, spec)

    loaded = spec_store.read_spec(root)
    assert loaded["version"] == 2
    assert loaded["content"] == "v2 content"


def _register_project(server, tmp):
    """Create a temp dir with .git and register it; return project id."""
    import tempfile, os
    d = tempfile.mkdtemp(dir=tmp)
    os.makedirs(os.path.join(d, ".git"), exist_ok=True)
    r = requests.post(f"{server}/api/projects", json={"path": d, "name": f"spec-test-{os.path.basename(d)}"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_spec_api_404_when_missing(server, tmp_path):
    pid = _register_project(server, str(tmp_path))
    r = requests.get(f"{server}/api/projects/{pid}/spec")
    assert r.status_code == 404


def test_spec_api_put_and_get(server, tmp_path):
    pid = _register_project(server, str(tmp_path))

    r = requests.put(f"{server}/api/projects/{pid}/spec", json={
        "title": "Test Spec",
        "content": "# Features\n\n- Login\n- Dashboard",
    })
    assert r.status_code == 200
    data = r.json()
    assert data["version"] == 1
    assert data["title"] == "Test Spec"
    assert "Login" in data["content"]

    r = requests.get(f"{server}/api/projects/{pid}/spec")
    assert r.status_code == 200
    assert r.json()["version"] == 1

    r = requests.put(f"{server}/api/projects/{pid}/spec", json={
        "content": "# Features\n\n- Login\n- Dashboard\n- Settings",
    })
    assert r.status_code == 200
    assert r.json()["version"] == 2
    assert "Settings" in r.json()["content"]
