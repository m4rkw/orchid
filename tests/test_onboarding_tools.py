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
    assert (target / ".orchid" / ".gitignore").read_text() == "*\n"

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
