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


def test_project_agents_roundtrip(server, homes):
    target = homes.tmp / "ag"
    target.mkdir()
    pid = requests.post(f"{server}/api/projects", json={"path": str(target)}, timeout=5).json()["id"]

    roles = requests.get(f"{server}/api/projects/{pid}/agents", timeout=5).json()
    by_slug = {r["slug"]: r for r in roles}
    assert by_slug["orchestrator"]["enabled"] is True
    assert by_slug["router"]["enabled"] is False and by_slug["router"]["note"]
    assert {r["slug"] for r in roles if r["enabled"]} == {"orchestrator", "worker", "reviewer", "verifier"}

    payload = [{**r, "enabled": False} if r["slug"] == "reviewer" else r for r in roles]
    updated = requests.put(f"{server}/api/projects/{pid}/agents", json={"roles": payload}, timeout=5).json()
    assert {r["slug"] for r in updated if r["enabled"]} == {"orchestrator", "worker", "verifier"}
    again = requests.get(f"{server}/api/projects/{pid}/agents", timeout=5).json()
    assert {r["slug"] for r in again if r["enabled"]} == {"orchestrator", "worker", "verifier"}


def test_project_plans_listing_and_404(server, homes):
    from orchid.store import plan_store

    target = homes.tmp / "pl"
    target.mkdir()
    created = requests.post(f"{server}/api/projects", json={"path": str(target)}, timeout=5).json()
    pid, root = created["id"], created["root"]

    assert requests.get(f"{server}/api/projects/{pid}/plans", timeout=5).json() == []
    plan_id = plan_store.new_plan_id()
    plan_store.write_plan(
        __import__("pathlib").Path(root),
        {"version": 1, "id": plan_id, "title": "P", "goal": "g", "status": "active", "steps": [],
         "updated_at": "2026-06-12T00:00:00+00:00"},
    )
    listed = requests.get(f"{server}/api/projects/{pid}/plans", timeout=5).json()
    assert [p["id"] for p in listed] == [plan_id]
    assert requests.get(f"{server}/api/projects/{pid}/plans/{plan_id}", timeout=5).json()["title"] == "P"
    assert requests.get(f"{server}/api/projects/{pid}/plans/pln_deadbeef00", timeout=5).status_code == 404


def test_patch_project_intent(server, homes):
    target = homes.tmp / "intent"
    target.mkdir()
    pid = requests.post(f"{server}/api/projects", json={"path": str(target)}, timeout=5).json()["id"]
    r = requests.patch(f"{server}/api/projects/{pid}", json={
        "intent": "goal", "goal": "Ship v2", "review_mode": "autonomous",
    }, timeout=5)
    assert r.status_code == 200
    p = r.json()
    assert p["intent"] == "goal" and p["goal"] == "Ship v2" and p["review_mode"] == "autonomous"
    # verify persistence
    p2 = next(p for p in requests.get(f"{server}/api/projects", timeout=5).json() if p["id"] == pid)
    assert p2["intent"] == "goal"


def test_project_activity(server, homes):
    import subprocess
    target = homes.tmp / "actproj"
    target.mkdir()
    subprocess.run(["git", "init", str(target)], check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=str(target), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=str(target), check=True, capture_output=True)
    (target / "f.txt").write_text("x")
    subprocess.run(["git", "add", "."], cwd=str(target), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(target), check=True, capture_output=True)
    pid = requests.post(f"{server}/api/projects", json={"path": str(target)}, timeout=5).json()["id"]
    activity = requests.get(f"{server}/api/projects/{pid}/activity", timeout=5).json()
    assert len(activity) >= 1
    assert activity[0]["message"] == "init"


def test_project_reviews_crud(server, homes):
    from orchid.store import review_store
    target = homes.tmp / "revproj"
    target.mkdir()
    pid = requests.post(f"{server}/api/projects", json={"path": str(target)}, timeout=5).json()["id"]
    review_store.write_review(target.resolve(), {
        "id": "rev_aabb01",
        "project_id": pid,
        "branch": "feat/x",
        "summary": "Added x",
        "status": "pending",
        "reviewer_notes": None,
        "created_at": "2026-01-01T00:00:00Z",
    })
    reviews = requests.get(f"{server}/api/projects/{pid}/reviews", timeout=5).json()
    assert len(reviews) == 1
    assert reviews[0]["branch"] == "feat/x"
    detail = requests.get(f"{server}/api/projects/{pid}/reviews/rev_aabb01", timeout=5).json()
    assert detail["summary"] == "Added x"
    assert requests.get(f"{server}/api/projects/{pid}/reviews/rev_000000", timeout=5).status_code == 404


def test_only_orchid_created_sessions_are_surfaced(server_app, homes):
    """A terminal-started transcript shares the project's SDK catalog but must
    never appear in Orchid's session list or count."""
    from orchid.models import SessionSummary

    url, app = server_app.url, server_app.app
    target = homes.tmp / "mixed"
    target.mkdir()
    pid = requests.post(f"{url}/api/projects", json={"path": str(target)}, timeout=5).json()["id"]

    async def list_sessions(root, flags):
        return [
            SessionSummary(id="orchid-sid", created_by="orchid", updated_at="2026-06-12T09:00:00+00:00"),
            SessionSummary(id="terminal-sid", created_by="external", updated_at="2026-06-12T08:00:00+00:00"),
        ]

    app.state.catalog.list_sessions = list_sessions

    listed = requests.get(f"{url}/api/projects/{pid}/sessions", timeout=5).json()
    assert [s["id"] for s in listed] == ["orchid-sid"]

    project = next(p for p in requests.get(f"{url}/api/projects", timeout=5).json() if p["id"] == pid)
    assert project["session_count"] == 1


def test_meta_project_children(server, homes):
    meta = homes.tmp / "meta"
    meta.mkdir()
    child1 = homes.tmp / "child1"
    child1.mkdir()
    child2 = homes.tmp / "child2"
    child2.mkdir()

    mp = requests.post(f"{server}/api/projects", json={"path": str(meta), "name": "Meta"}, timeout=5).json()
    c1 = requests.post(f"{server}/api/projects", json={"path": str(child1), "name": "Child1"}, timeout=5).json()
    c2 = requests.post(f"{server}/api/projects", json={"path": str(child2), "name": "Child2"}, timeout=5).json()

    r = requests.patch(f"{server}/api/projects/{mp['id']}", json={
        "project_type": "meta",
        "children": [c1["id"], c2["id"]],
    }, timeout=5)
    assert r.status_code == 200
    p = r.json()
    assert p["project_type"] == "meta"
    assert p["children"] == [c1["id"], c2["id"]]

    listed = next(p for p in requests.get(f"{server}/api/projects", timeout=5).json() if p["id"] == mp["id"])
    assert listed["project_type"] == "meta"
    assert listed["children"] == [c1["id"], c2["id"]]
