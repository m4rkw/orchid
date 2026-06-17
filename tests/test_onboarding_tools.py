import pytest

from orchid.bus import EventBus
from orchid.claude.catalog import Catalog
from orchid.claude.onboarding import build_onboarding_tools
from orchid.services import ProjectService
from orchid.store.registry import Registry

pytestmark = pytest.mark.asyncio


@pytest.fixture
def harness(settings):
    bus = EventBus()
    registry = Registry(settings.registry_path)
    service = ProjectService(registry, Catalog(), bus, settings)
    tools = {t.name: t for t in build_onboarding_tools(service, bus)}
    return bus, registry, tools


def _text_of(result):
    return result["content"][0]["text"]


async def test_register_project_full_flow(harness, homes):
    bus, registry, tools = harness
    sub = bus.subscribe({"onboarding"})
    target = homes.tmp / "demo"
    target.mkdir()

    out = _text_of(await tools["register_project"].handler({"path": str(target), "name": "Demo"}))
    assert "Registered 'Demo'" in out and "sidebar" in out

    assert registry.find_by_root(target) is not None
    assert (target / ".orchid" / "project.json").exists()
    assert "!spec.json" in (target / ".orchid" / ".gitignore").read_text()

    types = set()
    while sub.queue.qsize():
        types.add(sub.queue.get_nowait()["type"])
    assert {"project_added", "project_registered"} <= types

    again = _text_of(await tools["register_project"].handler({"path": str(target), "name": "Demo"}))
    assert "already registered" in again


async def test_register_project_rejects_bad_paths(harness, homes):
    _bus, registry, tools = harness
    out = _text_of(await tools["register_project"].handler({"path": str(homes.tmp / "nope"), "name": "X"}))
    assert "Error" in out and "does not exist" in out
    assert registry.list() == []

    f = homes.tmp / "file.txt"
    f.write_text("x")
    out = _text_of(await tools["register_project"].handler({"path": str(f), "name": "X"}))
    assert "Error" in out and "not a directory" in out


async def test_list_directory(harness, homes):
    _bus, _registry, tools = harness
    target = homes.tmp / "proj"
    (target / "sub").mkdir(parents=True)
    (target / "a.py").write_text("x")
    out = _text_of(await tools["list_directory"].handler({"path": str(target)}))
    assert "d sub" in out and "f a.py" in out
    out = _text_of(await tools["list_directory"].handler({"path": str(homes.tmp / "missing")}))
    assert "does not exist" in out


async def test_write_agents_md_and_assign_roles(harness, homes):
    from orchid.claude import roles

    bus, _registry, tools = harness
    sub = bus.subscribe({"onboarding"})
    target = homes.tmp / "proj"
    target.mkdir()

    out = _text_of(await tools["write_agents_md"].handler({"path": str(target), "content": "# Proj\nHello"}))
    assert "Wrote" in out
    assert (target / "AGENTS.md").read_text() == "# Proj\nHello\n"  # trailing newline added

    out = _text_of(await tools["assign_roles"].handler(
        {"path": str(target), "enabled": "orchestrator, worker, verifier"}
    ))
    assert "Enabled roles" in out
    enabled = {r.slug for r in roles.resolve_roles(target) if r.enabled}
    assert enabled == {"orchestrator", "worker", "verifier"}  # reviewer disabled vs default

    types = {sub.queue.get_nowait()["type"] for _ in range(sub.queue.qsize())}
    assert {"agents_md_written", "roles_assigned"} <= types


async def test_write_agents_md_rejects_bad_dir(harness, homes):
    _bus, _registry, tools = harness
    out = _text_of(await tools["write_agents_md"].handler({"path": str(homes.tmp / "nope"), "content": "x"}))
    assert "Error" in out and "not a directory" in out


async def test_git_init(harness, homes):
    _bus, _registry, tools = harness
    target = homes.tmp / "newproj"
    target.mkdir()
    out = _text_of(await tools["git_init"].handler({"path": str(target)}))
    assert "Initialized" in out
    assert (target / ".git").is_dir()
    out = _text_of(await tools["git_init"].handler({"path": str(target)}))
    assert "already has a .git" in out


async def test_set_project_intent(harness, homes):
    bus, _registry, tools = harness
    target = homes.tmp / "intented"
    target.mkdir()
    await tools["register_project"].handler({"path": str(target), "name": "Intented"})
    out = _text_of(await tools["set_project_intent"].handler({
        "path": str(target), "intent": "goal",
        "goal": "Build a REST API", "review_mode": "manual",
    }))
    assert "intent=goal" in out
    from orchid.store import project_store
    file = project_store.read_project_file(target)
    assert file["intent"] == "goal"
    assert file["goal"] == "Build a REST API"
    assert file["review_mode"] == "manual"


async def test_set_project_intent_validates(harness, homes):
    _bus, _registry, tools = harness
    target = homes.tmp / "valproj"
    target.mkdir()
    out = _text_of(await tools["set_project_intent"].handler({
        "path": str(target), "intent": "bad", "goal": "", "review_mode": "manual",
    }))
    assert "Error" in out


async def test_ask_choice_publishes_choice_prompt(harness, homes):
    bus, _registry, tools = harness
    sub = bus.subscribe({"onboarding"})
    out = _text_of(await tools["ask_choice"].handler({
        "question": "What's the intent?",
        "options": "Ad-hoc changes, Working towards a goal",
    }))
    assert "quick-reply buttons" in out

    evt = sub.queue.get_nowait()
    assert evt["type"] == "choice_prompt"
    payload = evt["payload"]
    assert payload["question"] == "What's the intent?"
    assert payload["options"] == ["Ad-hoc changes", "Working towards a goal"]  # trimmed
    assert isinstance(payload["id"], str) and payload["id"]


async def test_ask_choice_validates(harness, homes):
    _bus, _registry, tools = harness
    out = _text_of(await tools["ask_choice"].handler({"question": "Q?", "options": "  ,  "}))
    assert "Error" in out
    out = _text_of(await tools["ask_choice"].handler({"question": "", "options": "a,b"}))
    assert "Error" in out


async def test_inspect_directory(harness, homes):
    _bus, _registry, tools = harness
    target = homes.tmp / "inspectme"
    target.mkdir()
    (target / "README.md").write_text("# InspectMe\nA test project.")
    (target / "pyproject.toml").write_text("[project]\nname='x'")
    (target / "main.py").write_text("print('hi')")
    out = _text_of(await tools["inspect_directory"].handler({"path": str(target)}))
    assert "proposed name: inspectme" in out
    assert "pyproject.toml" in out
    assert "A test project." in out
    assert ".py" in out


async def test_scaffold_project(harness, homes):
    bus, _registry, tools = harness
    sub = bus.subscribe({"onboarding"})
    target = homes.tmp / "scaffolded"
    out = _text_of(await tools["scaffold_project"].handler({
        "path": str(target), "name": "Scaffolded", "project_type": "application",
    }))
    assert "Scaffolded" in out
    assert target.is_dir()
    assert (target / ".git").is_dir()
    assert (target / ".orchid" / "project.json").exists()
    from orchid.store import project_store
    file = project_store.read_project_file(target)
    assert file["project_type"] == "application"


async def test_scaffold_meta_project(harness, homes):
    _bus, _registry, tools = harness
    target = homes.tmp / "metaproj"
    out = _text_of(await tools["scaffold_project"].handler({
        "path": str(target), "name": "MetaProj", "project_type": "meta",
    }))
    assert "meta" in out
    from orchid.store import project_store
    file = project_store.read_project_file(target)
    assert file["project_type"] == "meta"


async def test_add_remove_child_project(harness, homes):
    bus, registry, tools = harness
    parent = homes.tmp / "parent"
    child = homes.tmp / "child"
    await tools["scaffold_project"].handler({
        "path": str(parent), "name": "Parent", "project_type": "meta",
    })
    await tools["scaffold_project"].handler({
        "path": str(child), "name": "Child", "project_type": "application",
    })
    from orchid.store import project_store
    child_file = project_store.read_project_file(child)
    child_id = child_file["id"]

    out = _text_of(await tools["add_child_project"].handler({
        "parent_path": str(parent), "child_project_id": child_id,
    }))
    assert child_id in out
    parent_file = project_store.read_project_file(parent)
    assert child_id in parent_file["children"]

    out = _text_of(await tools["add_child_project"].handler({
        "parent_path": str(parent), "child_project_id": child_id,
    }))
    assert "already" in out

    out = _text_of(await tools["remove_child_project"].handler({
        "parent_path": str(parent), "child_project_id": child_id,
    }))
    assert "Removed" in out
    parent_file = project_store.read_project_file(parent)
    assert child_id not in parent_file["children"]
