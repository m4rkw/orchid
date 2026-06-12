import os

import requests


def test_health(server):
    data = requests.get(f"{server}/api/health", timeout=5).json()
    assert data["version"]
    assert data["sdk_version"]
    assert "orchid_home" in data


def test_project_crud_roundtrip(server, homes):
    assert requests.get(f"{server}/api/projects", timeout=5).json() == []

    target = homes.tmp / "p1"
    target.mkdir()
    r = requests.post(f"{server}/api/projects", json={"path": str(target)}, timeout=5)
    assert r.status_code == 201, r.text
    project = r.json()
    assert project["name"] == "p1"
    assert project["root"] == str(target.resolve())
    assert project["session_count"] == 0

    listed = requests.get(f"{server}/api/projects", timeout=5).json()
    assert [p["id"] for p in listed] == [project["id"]]

    sessions = requests.get(f"{server}/api/projects/{project['id']}/sessions", timeout=5)
    assert sessions.status_code == 200 and sessions.json() == []

    r = requests.delete(f"{server}/api/projects/{project['id']}", timeout=5)
    assert r.status_code == 204
    assert requests.get(f"{server}/api/projects", timeout=5).json() == []
    assert requests.delete(f"{server}/api/projects/{project['id']}", timeout=5).status_code == 404


def test_duplicate_registration_409_even_via_symlink(server, homes):
    target = homes.tmp / "real"
    target.mkdir()
    link = homes.tmp / "alias"
    os.symlink(target, link)

    assert requests.post(f"{server}/api/projects", json={"path": str(target)}, timeout=5).status_code == 201
    r = requests.post(f"{server}/api/projects", json={"path": str(link)}, timeout=5)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "ALREADY_REGISTERED"


def test_bad_paths_rejected(server, homes):
    r = requests.post(f"{server}/api/projects", json={"path": str(homes.tmp / "ghost")}, timeout=5)
    assert r.status_code == 400 and r.json()["error"]["code"] == "PATH_NOT_FOUND"

    f = homes.tmp / "afile"
    f.write_text("x")
    r = requests.post(f"{server}/api/projects", json={"path": str(f)}, timeout=5)
    assert r.status_code == 400 and r.json()["error"]["code"] == "NOT_A_DIRECTORY"


def test_sessions_unknown_project_404(server):
    r = requests.get(f"{server}/api/projects/prj_nope/sessions", timeout=5)
    assert r.status_code == 404 and r.json()["error"]["code"] == "PROJECT_NOT_FOUND"
