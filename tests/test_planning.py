import pytest

from orchid.bus import EventBus
from orchid.claude.planning import build_plan_tools
from orchid.store import plan_store

pytestmark = pytest.mark.asyncio


@pytest.fixture
def harness(tmp_path):
    bus = EventBus()
    tools = {t.name: t for t in build_plan_tools(tmp_path, "prj_x", bus)}
    return tmp_path, bus, tools


def _text(result):
    return result["content"][0]["text"]


def _id(text):
    # first token that looks like a plan id
    return next(tok for tok in text.replace("\n", " ").split() if tok.startswith("pln_"))


async def test_create_with_inline_steps_persists_and_emits(harness):
    root, bus, tools = harness
    sub = bus.subscribe({"sidebar"})
    out = _text(await tools["create_plan"].handler(
        {"title": "Ship it", "goal": "deliver X", "steps": "do a\ndo b"}
    ))
    pid = _id(out)
    on_disk = plan_store.read_plan(root, pid)
    assert on_disk["title"] == "Ship it"
    assert [s["title"] for s in on_disk["steps"]] == ["do a", "do b"]
    evt = sub.queue.get_nowait()
    assert evt["type"] == "plan_upserted"
    assert evt["payload"]["project_id"] == "prj_x"
    assert evt["payload"]["plan"]["id"] == pid


async def test_add_and_update_step(harness):
    root, _bus, tools = harness
    pid = _id(_text(await tools["create_plan"].handler({"title": "P", "goal": "", "steps": ""})))
    out = _text(await tools["add_step"].handler({"plan_id": pid, "title": "build", "roles": "worker, verifier"}))
    step_id = next(s["id"] for s in plan_store.read_plan(root, pid)["steps"])
    assert plan_store.read_plan(root, pid)["steps"][0]["roles"] == ["worker", "verifier"]

    await tools["update_step"].handler({"plan_id": pid, "step_id": step_id, "status": "done"})
    assert plan_store.read_plan(root, pid)["steps"][0]["status"] == "done"

    bad = await tools["update_step"].handler({"plan_id": pid, "step_id": step_id, "status": "nonsense"})
    assert bad.get("is_error") is True


async def test_set_plan_status_and_listing(harness):
    root, _bus, tools = harness
    pid = _id(_text(await tools["create_plan"].handler({"title": "P", "goal": "g", "steps": "x"})))
    await tools["set_plan_status"].handler({"plan_id": pid, "status": "done"})
    assert plan_store.read_plan(root, pid)["status"] == "done"

    listing = _text(await tools["list_plans"].handler({}))
    assert pid in listing and "0/1 steps" in listing

    missing = await tools["get_plan"].handler({"plan_id": "pln_deadbeef00"})
    assert missing.get("is_error") is True
