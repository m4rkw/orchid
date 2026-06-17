import pytest

from orchid.bus import EventBus
from orchid.claude.architecture_tools import build_architecture_tools
from orchid.store import architecture_store


def _text_of(result):
    return result["content"][0]["text"]


def test_markdown_doc_roundtrip_handles_special_titles(tmp_path):
    from orchid.store.markdown_doc import read_doc, write_doc
    p = tmp_path / "d.md"
    write_doc(p, {"version": 1, "title": "A: B — c", "status": "active",
                  "content": "# H\n\nbody: with a colon\n"})
    got = read_doc(p)
    assert got["title"] == "A: B — c" and got["version"] == 1
    assert "body: with a colon" in got["content"]
    # the body is human-readable markdown on disk, not an escaped JSON string
    raw = p.read_text()
    assert "\n# H\n" in raw and "\\n" not in raw


def test_legacy_json_is_read_and_migrated(tmp_path):
    import json as _json
    from orchid.store.project_store import orchid_dir
    d = orchid_dir(tmp_path)
    d.mkdir(parents=True)
    legacy = d / "architecture.json"
    legacy.write_text(_json.dumps(
        {"version": 2, "title": "A", "content": "legacy body", "status": "active"}))
    # read falls back to the legacy json
    got = architecture_store.read_architecture(tmp_path)
    assert got and got["content"] == "legacy body" and got["version"] == 2
    # writing migrates to markdown and removes the json
    architecture_store.write_architecture(tmp_path, got)
    assert architecture_store.architecture_path(tmp_path).exists()
    assert not legacy.exists()
    assert architecture_store.read_architecture(tmp_path)["content"] == "legacy body"


def test_store_roundtrip(tmp_path):
    assert architecture_store.read_architecture(tmp_path) is None
    architecture_store.write_architecture(
        tmp_path, {"version": 1, "title": "A", "content": "X", "status": "active"}
    )
    a = architecture_store.read_architecture(tmp_path)
    assert a["content"] == "X"
    assert architecture_store.architecture_path(tmp_path).name == "architecture.md"


@pytest.mark.asyncio
async def test_tools_create_update_and_emit(tmp_path):
    bus = EventBus()
    sub = bus.subscribe({"sidebar"})
    tools = {t.name: t for t in build_architecture_tools(tmp_path, "prj", bus)}

    assert "No architecture" in _text_of(await tools["get_architecture"].handler({}))

    out = _text_of(await tools["update_architecture"].handler(
        {"title": "Arch", "content": "# Components\nstuff"}))
    assert "v1" in out
    a = architecture_store.read_architecture(tmp_path)
    assert a["version"] == 1 and "Components" in a["content"]

    out = _text_of(await tools["update_architecture"].handler({"content": "more"}))
    assert "v2" in out

    types = set()
    while not sub.queue.empty():
        types.add(sub.queue.get_nowait()["type"])
    assert "architecture_updated" in types


@pytest.mark.asyncio
async def test_tools_section_replace(tmp_path):
    bus = EventBus()
    tools = {t.name: t for t in build_architecture_tools(tmp_path, "prj", bus)}
    await tools["update_architecture"].handler({"content": "# Overview\nold\n\n# Data\nd"})
    out = _text_of(await tools["update_architecture"].handler(
        {"section": "Overview", "content": "new"}))
    assert "v2" in out
    a = architecture_store.read_architecture(tmp_path)
    assert "new" in a["content"] and "# Data" in a["content"]

    miss = _text_of(await tools["update_architecture"].handler(
        {"section": "Nope", "content": "x"}))
    assert "not found" in miss
