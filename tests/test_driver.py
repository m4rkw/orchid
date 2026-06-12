import asyncio

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, SystemMessage, TextBlock

from orchid.bus import EventBus
from orchid.claude.driver import SessionDriver
from orchid.claude.runner import RunnerSpec

pytestmark = pytest.mark.asyncio


def init_msg(sid="sid-1"):
    return SystemMessage(subtype="init", data={"session_id": sid})


def text_msg(text):
    return AssistantMessage(content=[TextBlock(text=text)], model="m")


def result_msg(sid="sid-1", **over):
    base = dict(
        subtype="success",
        duration_ms=100,
        duration_api_ms=90,
        is_error=False,
        num_turns=1,
        session_id=sid,
        total_cost_usd=0.01,
    )
    base.update(over)
    return ResultMessage(**base)


async def drain_until(sub, type_, timeout=2.0):
    events = []
    async with asyncio.timeout(timeout):
        while True:
            evt = await sub.queue.get()
            events.append(evt)
            if evt["type"] == type_:
                return events


def make_driver(fake_runner_cls, scripts, bus, hold_open=True):
    runner = fake_runner_cls(scripts)
    specs = []

    def spec_factory(sid):
        spec = RunnerSpec(resume=sid)
        specs.append(spec)
        return spec

    return runner, specs, SessionDriver(runner, spec_factory, bus, topic="onboarding", hold_open=hold_open)


async def test_happy_turn_event_order(fake_runner):
    bus = EventBus()
    sub = bus.subscribe({"onboarding"})
    runner, specs, driver = make_driver(
        fake_runner, [[[init_msg(), text_msg("hello"), result_msg()]]], bus
    )
    await driver.prompt("hi")
    events = await drain_until(sub, "turn_completed")
    types = [e["type"] for e in events]
    assert types == ["turn_started", "message", "message", "turn_completed"]
    assert events[1]["payload"]["message"]["role"] == "assistant"
    assert events[2]["payload"]["message"]["role"] == "result"
    assert events[3]["payload"]["total_cost_usd"] == 0.01
    assert driver.session_id == "sid-1"
    assert specs[0].resume is None
    await driver.aclose()


async def test_hold_open_reuses_client(fake_runner):
    bus = EventBus()
    sub = bus.subscribe({"onboarding"})
    scripts = [[[init_msg(), result_msg()], [result_msg()]]]  # one client, two turns
    runner, _specs, driver = make_driver(fake_runner, scripts, bus)
    await driver.prompt("one")
    await drain_until(sub, "turn_completed")
    await driver.prompt("two")
    await drain_until(sub, "turn_completed")
    assert len(runner.opened) == 1
    assert runner.opened[0][1].queries == ["one", "two"]
    await driver.aclose()


async def test_error_emits_event_and_drops_client(fake_runner):
    bus = EventBus()
    sub = bus.subscribe({"onboarding"})
    scripts = [
        [[init_msg(), RuntimeError("boom")]],  # client 1 dies mid-stream
        [[result_msg("sid-1")]],  # client 2 resumes
    ]
    runner, specs, driver = make_driver(fake_runner, scripts, bus)
    await driver.prompt("hi")
    events = await drain_until(sub, "error")
    assert "boom" in events[-1]["payload"]["message"]
    await driver.prompt("again")
    await drain_until(sub, "turn_completed")
    assert len(runner.opened) == 2
    assert specs[1].resume == "sid-1"  # context survives the crash via resume
    await driver.aclose()


async def test_reset_starts_fresh_session(fake_runner):
    bus = EventBus()
    sub = bus.subscribe({"onboarding"})
    scripts = [[[init_msg("sid-1"), result_msg("sid-1")]], [[init_msg("sid-2"), result_msg("sid-2")]]]
    runner, specs, driver = make_driver(fake_runner, scripts, bus)
    await driver.prompt("one")
    await drain_until(sub, "turn_completed")
    await driver.reset()
    await driver.prompt("two")
    await drain_until(sub, "turn_completed")
    assert driver.session_id == "sid-2"
    assert len(specs) == 2 and specs[1].resume is None
    assert runner.opened[0][1].closed is True
    await driver.aclose()


async def test_non_hold_open_closes_after_burst(fake_runner):
    bus = EventBus()
    sub = bus.subscribe({"onboarding"})
    runner, _specs, driver = make_driver(
        fake_runner, [[[init_msg(), result_msg()]]], bus, hold_open=False
    )
    await driver.prompt("hi")
    await drain_until(sub, "turn_completed")
    await asyncio.sleep(0.05)  # let the run loop hit the queue-empty close
    assert runner.opened[0][1].closed is True
    await driver.aclose()
